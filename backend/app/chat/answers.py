"""Compose cited nutrition answers from applicable KB rules and envelope context.

Escalation runs before retrieval. Patient-role requests with a REJECTED envelope
are refused; PROPOSED/EDITED envelope values are not quoted as personal targets.
APPROVED values prefer exact constraint provenance, with legacy trace matching
as a fallback. Guideline anchors and supporting rules are checked for patient
applicability when context is available. Dish facts supplement rule citations.

An answered response requires a citation. The default path is deterministic;
an injected LLM adapter receives the assembled text but its output is not
revalidated here. See ``docs/ARCHITECTURE.md`` for grounding and scope policy.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.app.chat import escalation, retrieval
from backend.app.kb.graph_store import KBGraph
from backend.app.chat.llm import LLMAdapter

__all__ = ["answer", "detect_nutrients", "format_value", "MAX_ANSWER_CHUNKS"]

MAX_ANSWER_CHUNKS = 3

# Rulebook nutrients whose constraint values are per-kg coefficients (see
# rules/engine.py ``_PER_KG_NUTRIENTS``). They must never be rendered as
# absolute daily doses.
_PER_KG_NUTRIENTS = {"energy_kcal", "protein_g"}

# Internal rule families that must never anchor a patient-facing citation:
# they encode conflict-resolution bookkeeping and internal safety policy, not
# guideline content a patient should be pointed at.
_INTERNAL_RULE_PREFIXES = ("CONFLICT-", "SAFETY-")

# Lifecycle edits use this source ID so clinician-authored values do not claim guideline authorship.
_CLINICIAN_EDIT_RULE_ID = "CLINICIAN-EDIT"

# Condition fields from the rulebook (mirrors rules/engine.py).
_MULTISLOT_CONDITION_FIELDS = {"diagnoses", "meds"}
_NUMERIC_CONDITION_FIELDS = {
    "age", "weight_kg", "bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL",
    "hba1c_pct",
}
# Numeric fields the engine guards against unknown values (a missing lab is
# stored as a -1.0 sentinel and must never satisfy a numeric test).
_UNKNOWN_GUARDED_FIELDS = {"bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL", "hba1c_pct"}

# Fixed, number-free responses for non-approved / declined envelopes.
_PENDING_REVIEW_SENTENCE = (
    "A nutrition plan has been drawn up for you, but it has not been approved "
    "by your clinician yet, so I can't quote your personal targets. Please "
    "talk to your clinician, who can confirm the plan with you."
)
_SCOPE_DECLINED_ANSWER = (
    "This proposal was declined — please talk to your clinician. CareLoop "
    "could not put together a suitable nutrition plan for you at the moment, "
    "so please let your clinician or dietitian guide any dietary changes."
)

# Nutrient detection in the user's question -> canonical nutrient field.
_NUTRIENT_PATTERNS: dict[str, list[str]] = {
    "sodium_mg": [r"sodium", r"\bsalt\b", r"\bna\b"],
    "potassium_mg": [r"potassium"],
    "phosphorus_mg": [r"phosphorus", r"phosphate"],
    "protein_g": [r"protein"],
    "energy_kcal": [r"calorie", r"\benergy\b", r"\bkcal\b"],
    "fiber_g": [r"fiber", r"fibre"],
    "sat_fat_g": [r"saturated fat", r"\bsat\.? ?fat\b", r"\bsatfat\b"],
    "carbs_g": [r"carb", r"carbohydrate", r"\bstarch\b"],
    "fat_g": [r"\bfat\b"],
    "sugar_g": [r"\bsugar\b"],
}

_COMPILED_NUTRIENTS = {
    nutrient: [re.compile(p, re.IGNORECASE) for p in patterns]
    for nutrient, patterns in _NUTRIENT_PATTERNS.items()
}

# This order determines which nutrient receives the anchor when several match.
# Saturated-fat questions can also match total fat; prefer sat_fat_g first.
_NUTRIENT_ORDER = [
    "sodium_mg", "potassium_mg", "phosphorus_mg", "protein_g", "energy_kcal",
    "fiber_g", "sat_fat_g", "carbs_g", "fat_g", "sugar_g",
]

_PLAIN_LABELS = {
    "sodium_mg": "salt (sodium)",
    "potassium_mg": "potassium",
    "phosphorus_mg": "phosphorus",
    "protein_g": "protein",
    "energy_kcal": "calories",
    "fiber_g": "fibre",
    "sat_fat_g": "saturated fat",
    "carbs_g": "carbohydrate",
    "fat_g": "fat",
    "sugar_g": "sugar",
}


def detect_nutrients(question: str) -> list[str]:
    """Canonical nutrients mentioned in ``question``, canonical order."""
    lowered = str(question or "").lower()
    found = []
    for nutrient in _NUTRIENT_ORDER:
        if any(p.search(lowered) for p in _COMPILED_NUTRIENTS[nutrient]):
            found.append(nutrient)
    return found


def format_value(value: Any, unit: str) -> str:
    """Human formatting: 2000 mg -> '2 g'; integral floats lose the '.0'."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "mg" and num >= 1000:
        grams = num / 1000.0
        text = f"{grams:g}"
        return f"{text} g"
    if num == int(num):
        return f"{int(num)} {unit}".strip()
    return f"{num:g} {unit}".strip()


def _kind_phrase(kind: str) -> str:
    return {
        "max": "limit",
        "min": "minimum",
        "target": "target",
    }.get(kind, kind)


def _citation_of_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id"),
        "guideline": rule.get("guideline"),
        "section": rule.get("section"),
        "url": rule.get("url"),
        "verbatim_quote": rule.get("verbatim_quote"),
    }


def _rule_applies_to_patient(
    rule: dict[str, Any], patient: Optional[dict[str, Any]]
) -> bool:
    """Best-effort re-evaluation of a rulebook rule's conditions for a patient.

    Handles diagnosis/medication membership, pregnancy equality, and numeric
    comparisons. Missing numeric values and NaN fail; guarded fields also reject
    negative unknown sentinels. Pregnancy diagnoses count as pregnancy.
    Without patient context, all rules are treated as applicable.
    """
    if not patient:
        return True
    diagnoses = {str(d) for d in (patient.get("diagnoses") or [])}
    pregnant = bool(patient.get("pregnant")) or "pregnancy" in diagnoses
    for cond in rule.get("conditions") or []:
        field, op, value = cond.get("field"), cond.get("op"), cond.get("value")
        if field in _MULTISLOT_CONDITION_FIELDS:
            have = diagnoses if field == "diagnoses" else {
                str(m) for m in (patient.get("meds") or [])
            }
            wanted = [str(v) for v in (value or [])]
            if op == "in":
                if not any(v in have for v in wanted):
                    return False
            elif op == "not_in":
                if any(v in have for v in wanted):
                    return False
            else:
                return False
        elif field == "pregnant":
            if op != "eq" or pregnant != bool(value):
                return False
        elif field in _NUMERIC_CONDITION_FIELDS:
            try:
                num = float(patient.get(field))
            except (TypeError, ValueError):
                return False
            if num != num:  # NaN -> unknown
                return False
            if field in _UNKNOWN_GUARDED_FIELDS and num < 0:
                return False
            try:
                if op == "between":
                    lo, hi = value
                    if not (float(lo) <= num <= float(hi)):
                        return False
                elif op == "ge":
                    if not num >= float(value):
                        return False
                elif op == "gt":
                    if not num > float(value):
                        return False
                elif op == "le":
                    if not num <= float(value):
                        return False
                elif op == "lt":
                    if not num < float(value):
                        return False
                elif op == "eq":
                    if not num == float(value):
                        return False
                else:
                    return False
            except (TypeError, ValueError):
                return False
        else:
            return False
    return True


def _anchor_rule(
    kb: KBGraph,
    nutrients: list[str],
    role: str = "patient",
    patient: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """First applicable rule for the first detected nutrient with an eligible anchor.

    Nutrient order takes precedence; rules within each nutrient are sorted by
    decreasing priority then rule ID. Patient-role anchors exclude internal
    CONFLICT/SAFETY rules. Return None when no eligible rule exists.
    """
    for nutrient in nutrients:
        for rule in kb.rules_for_nutrient(nutrient):
            if role == "patient" and str(rule.get("rule_id", "")).startswith(
                _INTERNAL_RULE_PREFIXES
            ):
                continue
            if not _rule_applies_to_patient(rule, patient):
                continue
            return rule
    return None


def _status_of(envelope: dict[str, Any]) -> str:
    raw_status = envelope.get("status", "")
    return str(getattr(raw_status, "value", raw_status) or "")


def _target_is_unscaled_per_kg(envelope: dict[str, Any], target: dict[str, Any]) -> bool:
    """True when an envelope target still carries a raw per-kg coefficient.

    The engine scales per-kg coefficients by weight whenever the weight is
    known; the producing trace row then reads
    ``set <nutrient> <kind> = <coef> <unit>/kg/d -> <scaled> <unit>/d``.
    A row with the ``/kg/d`` marker but no ``-> <scaled>`` clause means the
    weight was unknown and the stored value is still the coefficient.
    """
    nutrient = target.get("nutrient", "")
    if nutrient not in _PER_KG_NUTRIENTS:
        return False
    kind = target.get("kind", "")
    for fired in envelope.get("fired_rules") or []:
        summary = str(fired.get("action_summary", "")).lower()
        if f"set {nutrient} {kind}" in summary and "/kg/d" in summary:
            return "->" not in summary
    return False


def _envelope_context(
    envelope: Optional[dict[str, Any]],
    nutrients: list[str],
    weight_kg: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    if not envelope:
        return None
    status = _status_of(envelope)
    targets = list(envelope.get("targets") or [])
    matched = [t for t in targets if t.get("nutrient") in nutrients] if nutrients else []
    if nutrients and not matched:
        return None
    chosen = matched or targets
    if not chosen:
        return None

    target = chosen[0]
    nutrient = target.get("nutrient", "")
    label = _PLAIN_LABELS.get(nutrient, nutrient)
    kind = target.get("kind", "")

    if status != "APPROVED":
        # Unapproved envelope context supplies a notice, never personal target numbers.
        sentence = (
            _PENDING_REVIEW_SENTENCE
            if status in ("PROPOSED", "EDITED")
            else _SCOPE_DECLINED_ANSWER
        )
        return {
            "envelope_id": envelope.get("envelope_id"),
            "status": status,
            "approved": False,
            "sentence": sentence,
            "citation": None,
            "edit_authored": False,
            "target": target,
        }

    amount = format_value(target.get("value"), target.get("unit", ""))
    if _target_is_unscaled_per_kg(envelope, target):
        value = target.get("value")
        try:
            coefficient = float(value)
        except (TypeError, ValueError):
            coefficient = None
        if coefficient is not None and weight_kg and weight_kg > 0:
            amount = format_value(coefficient * weight_kg, target.get("unit", ""))
        else:
            amount = f"{amount} per kg of body weight"
    if kind == "max":
        core = f"a daily {label} limit of {amount}"
    elif kind == "min":
        core = f"a daily {label} minimum of {amount}"
    else:
        core = f"a daily {label} target of {amount}"
    sentence = f"Your clinician-approved plan sets {core}."

    # Match exact constraint provenance before legacy trace inference; citations[0]
    # could attribute an edited number to an unrelated guideline.
    from shared.provenance import citation_for

    provenance = target.get("provenance") or {}
    matches = all(provenance.get(k) == target.get(k) for k in ("nutrient", "kind", "value", "unit"))
    citation = (provenance.get("citation") if matches else None) or citation_for(
        target, envelope.get("fired_rules") or []
    )
    return {
        "envelope_id": envelope.get("envelope_id"),
        "status": status,
        "approved": True,
        "sentence": sentence,
        "citation": citation,
        "edit_authored": bool(citation and citation.get("rule_id") == _CLINICIAN_EDIT_RULE_ID),
        "target": target,
    }


def _rule_sentence(rule: dict[str, Any], role: str) -> str:
    guideline = rule.get("guideline")
    section = rule.get("section")
    quote = rule.get("verbatim_quote")
    notes = rule.get("notes") or ""
    if quote:
        body = f"“{quote}”"
    elif notes:
        body = f"“{notes}”"
    else:
        body = "this section of the guideline applies"
    prefix = f"[{rule['rule_id']}] " if role == "clinician" else ""
    return f"{prefix}According to {guideline} ({section}): {body}"


def _constraint_sentences(
    rule: dict[str, Any], role: str, weight_kg: Optional[float] = None
) -> list[str]:
    """Render a rule's constraints as patient-safe sentences.

    Per-kg coefficients (25-35 kcal/kg, 0.8-1.3 g/kg protein, ...) are never
    printed as absolute daily doses: with a known body weight the computed
    daily value is shown, otherwise the sentence says "per kg of body weight".
    """
    sentences = []
    for constraint in rule.get("constraints", []):
        nutrient = constraint.get("nutrient")
        label = _PLAIN_LABELS.get(nutrient, nutrient)
        amount = format_value(constraint.get("value"), constraint.get("unit", ""))
        phrase = _kind_phrase(constraint.get("kind", ""))
        prefix = f"[{rule['rule_id']}] " if role == "clinician" else ""
        if nutrient in _PER_KG_NUTRIENTS:
            weight = None
            try:
                weight = float(weight_kg) if weight_kg is not None else None
            except (TypeError, ValueError):
                weight = None
            if weight is not None and weight > 0:
                daily = format_value(float(constraint.get("value", 0)) * weight,
                                     constraint.get("unit", ""))
                sentences.append(
                    f"{prefix}This guideline sets a {label} {phrase} of {daily} per day "
                    f"for a {weight:g} kg patient ({amount} per kg of body weight)."
                )
            else:
                sentences.append(
                    f"{prefix}This guideline sets a {label} {phrase} of {amount} "
                    f"per kg of body weight per day."
                )
        else:
            sentences.append(
                f"{prefix}This guideline sets a {label} {phrase} of {amount} per day."
            )
    return sentences


def _dish_sentences(hits: list[dict[str, Any]], role: str) -> list[str]:
    sentences = []
    for hit in hits:
        if hit.get("kind") != "dish":
            continue
        meta = hit.get("meta", {})
        name = meta.get("name") or meta.get("dish_id")
        nutrients = meta.get("nutrients", {})
        bits = []
        for nutrient in _NUTRIENT_ORDER:
            if nutrient in nutrients:
                unit = nutrient.rsplit("_", 1)[1] if "_" in nutrient else ""
                bits.append(f"{_PLAIN_LABELS.get(nutrient, nutrient)} "
                            f"{format_value(nutrients[nutrient], unit)}")
        prefix = f"[{meta.get('dish_id')}] " if role == "clinician" else ""
        if bits:
            sentences.append(f"{prefix}Per serving, {name} contains about "
                             f"{', '.join(bits[:4])}.")
        else:
            sentences.append(f"{prefix}{name} appears in the dish database.")
        if len(sentences) >= 2:
            break
    return sentences


def _patient_weight(
    patient: Optional[dict[str, Any]], envelope: Optional[dict[str, Any]]
) -> Optional[float]:
    """Best-available body weight (kg) for per-kg rendering."""
    weight: Any = (patient or {}).get("weight_kg")
    if weight is None and envelope:
        snapshot = envelope.get("patient_snapshot") or {}
        weight = snapshot.get("weight_kg")
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return None
    return weight if weight > 0 else None


def answer(
    question: str,
    kb: KBGraph,
    envelope: Optional[dict[str, Any]] = None,
    role: str = "patient",
    llm: Optional[LLMAdapter] = None,
    patient: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compose an answered, refused, or escalated response without changing clinical state.

    Returns a dict with keys: ``status`` (``answered`` | ``refused`` |
    ``escalated``), ``answer``, ``citations``, ``envelope``, ``retrieval`` and
    ``role``. ``role="clinician"`` keeps rule ids inline in the text; the
    patient view hides them from the prose but retains citation IDs.
    ``patient`` supplies applicability context and weight for per-kg rendering.
    The template path is deterministic. An optional ``llm`` may transform the
    final text; this function does not verify that transformation's grounding.
    """
    esc = escalation.check(question)
    if esc["escalate"]:
        return {
            "status": "escalated",
            "question": question,
            "answer": esc["reason"],
            "citations": [],
            "escalation": esc,
            "envelope": None,
            "retrieval": [],
            "role": role,
        }

    # Patient-role scope refusal follows escalation and does not expose guideline content.
    if role == "patient" and envelope is not None and _status_of(envelope) == "REJECTED":
        return {
            "status": "refused",
            "question": question,
            "answer": _SCOPE_DECLINED_ANSWER,
            "citations": [],
            "escalation": esc,
            "envelope": None,
            "retrieval": [],
            "role": role,
        }

    weight_kg = _patient_weight(patient, envelope)

    hits = retrieval.build_index(kb).retrieve(question, k=5)
    best_score = hits[0]["score"] if hits else 0.0
    nutrients = detect_nutrients(question)
    # Do not use personal target numbers to answer an unrelated question.
    relevant = bool(nutrients) or best_score > retrieval.MIN_SCORE
    env_ctx = _envelope_context(envelope, nutrients, weight_kg) if relevant else None

    parts: list[str] = []
    citations: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []

    # Prefer the current profile for rule applicability, then the frozen snapshot.
    applicability_patient = patient or (envelope or {}).get("patient_snapshot")

    # 1) Envelope numbers (approved only; pending/declined get fixed text).
    if env_ctx is not None:
        parts.append(env_ctx["sentence"])
        if env_ctx["citation"]:
            citations.append(env_ctx["citation"])
        claims.append({"text": env_ctx["sentence"], "source": "envelope",
                       "target": env_ctx.get("target") if env_ctx["approved"] else None,
                       "envelope_id": envelope.get("envelope_id"),
                       "version": envelope.get("version"), "citation": env_ctx["citation"]})

    # 2) Choose an applicable nutrient anchor independently of envelope approval.
    anchor = (
        _anchor_rule(kb, nutrients, role, applicability_patient)
        if nutrients
        else None
    )
    if nutrients and anchor is None and env_ctx is None and re.search(r"\b(how much|limit|target|daily)\b", question, re.I):
        hits, best_score = [], 0.0
    if anchor is not None:
        sentences = [_rule_sentence(anchor, role), *_constraint_sentences(anchor, role, weight_kg)[:2]]
        parts.extend(sentences)
        claims.extend({"text": text, "source": "rule", "citation": _citation_of_rule(anchor)} for text in sentences)
        citations.append(_citation_of_rule(anchor))

    # 3) Supporting retrieved chunks (rule chunks add citations, dish chunks
    #    add food facts).
    if anchor is not None or env_ctx is not None or best_score > retrieval.MIN_SCORE:
        used_anchor = anchor["rule_id"] if anchor else None
        for hit in hits:
            if len(parts) >= 1 + MAX_ANSWER_CHUNKS:
                break
            if hit["score"] <= retrieval.MIN_SCORE:
                break
            if hit.get("kind") == "rule":
                rule_id = hit["citation"]["rule_id"]
                if rule_id == used_anchor:
                    continue
                if applicability_patient is not None:
                    rule = kb.get_rule(rule_id)
                    if rule is not None and not _rule_applies_to_patient(
                        rule, applicability_patient
                    ):
                        continue
                parts.append(_rule_sentence_from_chunk(hit, role))
                claims.append({"text": parts[-1], "source": "rule", "citation": hit["citation"]})
                citations.append(hit["citation"])
            else:
                sentences = _dish_sentences([hit], role)
                parts.extend(sentences)
                claims.extend({"text": text, "source": "dish", "chunk_id": hit["chunk_id"]} for text in sentences)

    if not citations:
        return {
            "status": "refused",
            "question": question,
            "answer": (
                "I could not find guideline-backed information to answer that "
                "safely. Please check with your clinician or dietitian."
            ),
            "citations": [],
            "escalation": esc,
            "envelope": None,
            "retrieval": [
                {"chunk_id": h["chunk_id"], "kind": h["kind"], "score": h["score"]}
                for h in hits
            ],
            "role": role,
        }

    answer_text = " ".join(parts)

    if llm is not None:
        answer_text = llm.generate(
            answer_text,
            context={"question": question, "citations": citations},
        )

    envelope_summary = None
    if envelope:
        envelope_summary = {
            "envelope_id": envelope.get("envelope_id"),
            "status": envelope.get("status"),
            "approved": bool(env_ctx["approved"]) if env_ctx else envelope.get("status") == "APPROVED",
            "notice": (
                None
                if (env_ctx and env_ctx["approved"])
                else "This plan has not been approved by a clinician yet."
            ),
        }

    return {
        "status": "answered",
        "question": question,
        "answer": answer_text,
        "claims": claims,
        "citations": citations,
        "escalation": esc,
        "envelope": envelope_summary,
        "retrieval": [
            {"chunk_id": h["chunk_id"], "kind": h["kind"], "score": h["score"]}
            for h in hits
        ],
        "role": role,
    }


def _rule_sentence_from_chunk(hit: dict[str, Any], role: str) -> str:
    citation = hit["citation"]
    quote = citation.get("verbatim_quote")
    guideline = citation.get("guideline")
    section = citation.get("section")
    rule_id = citation.get("rule_id")
    prefix = f"[{rule_id}] " if role == "clinician" else ""
    if quote:
        body = f"“{quote}”"
    else:
        body = "this section of the guideline applies"
    return f"{prefix}According to {guideline} ({section}): {body}"
