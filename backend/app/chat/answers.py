"""Compose cited nutrition answers from applicable KB rules and envelope context.

Personal targets require APPROVED envelopes. Patient requests with REJECTED
envelopes are refused. Templates are deterministic and include citations.
Optional LLM rephrasing is not checked for grounding.
"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.app.chat import escalation, retrieval
from backend.app.chat.llm import LLMAdapter
from backend.app.kb.graph_store import KBGraph

__all__ = [
    "MAX_ANSWER_PROSE_PARTS",
    "answer",
    "detect_nutrients",
    "format_value",
]

# Supporting-text limit excludes the primary envelope or rule answer.
MAX_ANSWER_PROSE_PARTS = 3

# Trace row format: ``set <nutrient> <kind> = <coef> <unit>/kg/d`` with no
# ``-> <scaled>`` clause (weight was unknown at generation time).
_UNSCALED_COEFFICIENT_ROW = re.compile(
    r"set (?P<nutrient>\w+) (?P<kind>\w+) = (?P<value>-?[\d.]+) (?P<unit>\w+)/kg/d"
)

# Keep in sync with rules.engine: per-kg values are not daily doses.
_PER_KG_NUTRIENTS = {"energy_kcal", "protein_g"}

# Internal bookkeeping rules cannot anchor patient-facing citations.
_INTERNAL_RULE_PREFIXES = ("CONFLICT-", "SAFETY-")

# Prevents clinician-authored values from claiming guideline authorship.
_CLINICIAN_EDIT_RULE_ID = "CLINICIAN-EDIT"

# Mirrors rules/engine.py condition-field sets.
_MULTISLOT_CONDITION_FIELDS = {"diagnoses", "meds"}
_NUMERIC_CONDITION_FIELDS = {
    "age", "weight_kg", "bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL",
    "hba1c_pct",
}
# Missing labs are -1.0 sentinels and must never satisfy a numeric test.
_UNKNOWN_GUARDED_FIELDS = {"bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL", "hba1c_pct"}

# Number-free responses for non-approved / declined envelopes.
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

# Prefer saturated fat before total fat when a question matches both.
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
    """Canonical nutrients mentioned in ``question``, in ``_NUTRIENT_ORDER``."""
    lowered = question.lower()
    found = []
    for nutrient in _NUTRIENT_ORDER:
        if any(p.search(lowered) for p in _COMPILED_NUTRIENTS[nutrient]):
            found.append(nutrient)
    return found


def format_value(value: Any, unit: str) -> str:
    """Format a value for display without lossy rounding.

    Milligram values convert to grams only when the conversion is exact, so a
    MAX ceiling cannot round down and a MIN floor cannot round up.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "mg" and num >= 1000 and num % 10 == 0:
        # Multiples of 10 mg are exact in hundredths of a gram.
        grams = num / 1000.0
        text = f"{grams:.2f}".rstrip("0").rstrip(".")
        return f"{text} g"
    if num == int(num):
        return f"{int(num)} {unit}".strip()
    return f"{value} {unit}".strip()


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
    rule: dict[str, Any], patient: dict[str, Any] | None
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
                num = float(patient.get(field, 0))
            except (TypeError, ValueError):
                return False
            if math.isnan(num):  # NaN -> unknown
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
                    if num != float(value):
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
    patient: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
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
    """Detect an unscaled per-kg target from its matching source trace.

    Raw rows contain ``/kg/d`` without a ``-> <scaled>`` value. Match the
    current target, not an obsolete rule value. Clinician edits are daily doses.
    """
    nutrient = target.get("nutrient", "")
    if nutrient not in _PER_KG_NUTRIENTS:
        return False
    # Legacy clinician doses may equal a coefficient without being per-kg.
    citation = _target_citation(target, envelope.get("fired_rules") or [])
    if not citation or citation.get("rule_id") == _CLINICIAN_EDIT_RULE_ID:
        return False
    kind = target.get("kind", "")
    try:
        stored = float(target["value"])
    except (KeyError, TypeError, ValueError):
        return False
    for fired in envelope.get("fired_rules") or []:
        summary = str(fired.get("action_summary", "")).lower()
        if fired.get("rule_id") != citation.get("rule_id") or "superseded" in summary:
            continue
        if f"set {nutrient} {kind}" not in summary or "/kg/d" not in summary:
            continue
        if "->" in summary:
            continue
        # A raw row must match the selected source, value, and base unit.
        for match in _UNSCALED_COEFFICIENT_ROW.finditer(summary):
            if (match.group("nutrient") != nutrient or match.group("kind") != kind
                    or match.group("unit") != target.get("unit")):
                continue
            try:
                coefficient = float(match.group("value"))
            except ValueError:
                continue
            if abs(coefficient - stored) <= 0.005:
                return True
    return False


def _target_citation(target: dict[str, Any], fired_rules: list[dict[str, Any]]):
    """Resolve explicit exact-target provenance, or legacy trace if absent.

    Explicit but stale provenance is a failed attribution, not permission to
    borrow a convenient matching legacy source.
    """
    from shared.provenance import citation_for

    provenance = target.get("provenance")
    if provenance:
        if any(
            provenance.get(key) != target.get(key)
            for key in ("nutrient", "kind", "value", "unit")
        ):
            return None
        return provenance.get("citation")
    return citation_for(target, fired_rules)


def _envelope_context(
    envelope: dict[str, Any] | None,
    nutrients: list[str],
    weight_kg: float | None = None,
) -> dict[str, Any] | None:
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

    # A general envelope citation cannot establish who authored this value.
    citation = _target_citation(target, envelope.get("fired_rules") or [])
    if citation and not all(citation.get(key) for key in ("rule_id", "guideline", "section")):
        citation = None
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
    rule: dict[str, Any], role: str, weight_kg: float | None = None
) -> list[str]:
    """Render constraints, scaling per-kg values only with a positive weight.

    Without weight, retain the "per kg of body weight" qualifier.
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
    patient: dict[str, Any] | None, envelope: dict[str, Any] | None
) -> float | None:
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
    envelope: dict[str, Any] | None = None,
    role: str = "patient",
    llm: LLMAdapter | None = None,
    patient: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose an answered, refused, or escalated response without changing clinical state.

    Every result carries ``status`` (``answered`` | ``refused`` | ``escalated``),
    ``question``, ``answer``, ``citations``, ``escalation``, ``envelope``,
    ``retrieval``, and ``role``. Answered results also carry structured ``claims``;
    refused/escalated results omit that key. ``role="clinician"`` keeps rule IDs
    inline in the text. The patient view hides them from prose but retains
    citation IDs.
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
    # An approved personal value with no traceable citation is withheld; the
    # independent guideline anchor below never lends its citation to the number.
    if env_ctx is not None and env_ctx["approved"] and not env_ctx["citation"]:
        env_ctx = None

    parts: list[str] = []
    citations: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []

    # Prefer the current profile for rule applicability, then the frozen snapshot.
    applicability_patient = patient or (envelope or {}).get("patient_snapshot")

    if env_ctx is not None:
        parts.append(env_ctx["sentence"])
        if env_ctx["citation"]:
            citations.append(env_ctx["citation"])
        claims.append({"text": env_ctx["sentence"], "source": "envelope",
                       "target": env_ctx.get("target") if env_ctx["approved"] else None,
                       "envelope_id": (envelope or {}).get("envelope_id"),
                       "version": (envelope or {}).get("version"), "citation": env_ctx["citation"]})

    # General guideline anchors do not depend on personal-target approval.
    anchor = (
        _anchor_rule(kb, nutrients, role, applicability_patient)
        if nutrients
        else None
    )
    food_content_question = bool(re.search(
        r"\b(content|contains?|per serving)\b|\b(?:sugar|sodium|salt|protein|fat|carbs?|calories)\s+(?:is\s+)?in\b",
        question, re.IGNORECASE,
    ))
    if nutrients and anchor is None and env_ctx is None and not food_content_question:
        # Food composition is distinct from intake guidance. A personal intake
        # answer needs a relevant constraint, not an unrelated retrieval citation.
        hits, best_score = [], 0.0
    if anchor is not None:
        sentences = [_rule_sentence(anchor, role), *_constraint_sentences(anchor, role, weight_kg)[:2]]
        parts.extend(sentences)
        claims.extend({"text": text, "source": "rule", "citation": _citation_of_rule(anchor)} for text in sentences)
        citations.append(_citation_of_rule(anchor))

    if anchor is not None or env_ctx is not None or best_score > retrieval.MIN_SCORE:
        used_anchor = anchor["rule_id"] if anchor else None
        for hit in hits:
            if len(parts) >= 1 + MAX_ANSWER_PROSE_PARTS:
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
        # Lifecycle state is independent of which targets the question matched.
        approved = _status_of(envelope) == "APPROVED"
        envelope_summary = {
            "envelope_id": envelope.get("envelope_id"),
            "status": envelope.get("status"),
            "approved": approved,
            "notice": (
                None if approved
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
