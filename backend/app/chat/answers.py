"""Retrieval-grounded answer pipeline.

``answer(question, kb, envelope=None, role="patient")`` is the single entry
point. Pipeline order:

1. **Escalation filter** (``escalation.check``) — out-of-scope requests are
   escalated, never answered.
2. **Retrieval** (``retrieval.build_index``) — TF-IDF over KB rule + dish
   chunks.
3. **Composition** — the answer text is assembled *only* from retrieved chunk
   content plus (when an envelope is supplied) the envelope's own numbers.
   Nothing is invented: templates pick sentences, they never generate facts.
4. **Citation invariant** — an ``answered`` response always carries at least
   one citation with ``rule_id`` + ``guideline`` + ``section``. If no rule
   can be cited for the question, the answer is refused instead. The first
   citation always reflects the provenance of the answered number: a
   clinician-edited constraint cites the CLINICIAN-EDIT trace row, and
   guideline rules appear only as additional context and only when they
   apply to the patient.
5. **Low-confidence refusal** — if no nutrient is detected and the best
   retrieval score is below ``retrieval.MIN_SCORE``, refuse and suggest
   speaking with a clinician.

Envelope handling honours the approval gate (``core/approval_gate.py``):

* an **APPROVED** envelope's numbers are served as clinician-approved;
* a **PROPOSED** or **EDITED** envelope is never quoted numerically — the
  answer says a plan is pending clinician review (generic guideline content
  may still be cited);
* a **REJECTED** (out-of-scope) envelope yields one fixed, respectful
  see-your-clinician response regardless of the question — no numbers, no
  guideline content.

Per-kg rulebook coefficients (25-35 kcal/kg, 0.55-1.3 g/kg protein) are never
rendered as absolute daily doses: when the patient's weight is known the
computed daily value is shown, otherwise the text says "per kg of body weight".
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

# Trace rule id the envelope lifecycle records for a clinician-authored edit
# (see ``api/envelopes.py``). A value backed by this row was set by a
# clinician, not derived from a guideline rule, so it must be cited as the
# source of the number instead of any guideline rule for the nutrient.
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

# Longer/more specific patterns first so e.g. "saturated fat" also claims fat_g.
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
        text = f"{grams:.1f}".rstrip("0").rstrip(".")
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

    Mirrors ``rules/engine.py`` semantics: multislot membership for
    ``diagnoses``/``meds``, ``pregnant`` equality (the engine also encodes
    pregnancy as a diagnosis), and numeric comparisons where a missing lab
    (or the ``-1.0`` unknown sentinel, or NaN) never satisfies the test.

    With no patient context (``patient`` falsy) every rule is treated as
    applicable so pure-KB behaviour is unchanged.
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
                elif op == "ge" and not num >= float(value):
                    return False
                elif op == "gt" and not num > float(value):
                    return False
                elif op == "le" and not num <= float(value):
                    return False
                elif op == "lt" and not num < float(value):
                    return False
                elif op == "eq" and not num == float(value):
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
    """Highest-priority current KB rule covering the detected nutrients.

    ``rules_for_nutrient`` already sorts by priority DESC then rule_id, so the
    choice is deterministic (CKD rules outrank DASH/ADA/generic, and
    ``CKD-2024-*`` sorts before ``CONFLICT-*`` on ties).

    For the patient role, internal rule families (``CONFLICT-*`` conflict
    bookkeeping, ``SAFETY-*`` internal safety policy) are excluded from anchor
    selection: patients should be anchored to guideline content, not internal
    engine policy.

    When a patient context is passed, rules whose conditions do not apply to
    this patient (diagnoses, meds, labs) are skipped: a guideline rule must
    never be anchored for a patient it does not cover.
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
        # Numbers are only ever quoted for clinician-APPROVED envelopes.
        # PROPOSED/EDITED -> pending-review sentence; REJECTED -> the fixed
        # declined sentence. No numbers, no citations attached.
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

    # Cite the trace row that actually produced the quoted number — never fall
    # back to citations[0], which could attach an unrelated guideline (e.g.
    # after a clinician edit replaced the targets) to the quoted number.
    # A clinician-authored value (CLINICIAN-EDIT row) always wins over the
    # original guideline rows for the same nutrient: the edit replaced those
    # values, so the edit's provenance is the source of the answered number.
    edit_citation: Optional[dict[str, Any]] = None
    rule_citation: Optional[dict[str, Any]] = None
    for fired in envelope.get("fired_rules") or []:
        summary = str(fired.get("action_summary", "")).lower()
        if nutrient.split("_")[0] not in summary and nutrient not in summary:
            continue
        if str(fired.get("rule_id", "")) == _CLINICIAN_EDIT_RULE_ID:
            # Keep the latest matching edit row (multiple edits may be traced).
            edit_citation = fired.get("citation")
        elif rule_citation is None:
            rule_citation = fired.get("citation")
    citation = edit_citation or rule_citation
    return {
        "envelope_id": envelope.get("envelope_id"),
        "status": status,
        "approved": True,
        "sentence": sentence,
        "citation": citation,
        "edit_authored": edit_citation is not None,
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
    """Grounded, deterministic answer with mandatory citations.

    Returns a dict with keys: ``status`` (``answered`` | ``refused`` |
    ``escalated``), ``answer``, ``citations``, ``envelope``, ``retrieval`` and
    ``role``. ``role="clinician"`` keeps rule ids inline in the text; the
    patient view hides them from the prose (they remain in ``citations``).

    ``patient`` (optional patient record dict) enables per-kg constraint
    values to be scaled into computed daily amounts.
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

    # Out-of-scope gate: a REJECTED envelope means the patient has no CareLoop
    # nutrition plan at all (pregnancy, dialysis, ketoacidosis risk, ...).
    # Whatever the question, the only safe reply is the fixed see-your-
    # clinician response — no numbers, no guideline content.
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
    # The envelope is only consulted when the question is actually about the
    # patient's nutrition (detected nutrient or a relevant KB hit) — an
    # unrelated question must be refused, not answered from plan numbers.
    relevant = bool(nutrients) or best_score > retrieval.MIN_SCORE
    env_ctx = _envelope_context(envelope, nutrients, weight_kg) if relevant else None

    parts: list[str] = []
    citations: list[dict[str, Any]] = []

    # When the patient's APPROVED numbers are being quoted, every guideline
    # citation must be checked against this patient: a rule whose conditions
    # (diagnoses, meds, labs) do not apply must never be cited as if it
    # governed their plan. Generic guideline-only answers (no approved
    # envelope consulted) keep the plain retrieval-order anchor.
    applicability_patient = (
        patient if (env_ctx is not None and env_ctx.get("approved")) else None
    )

    # 1) Envelope numbers (approved only; pending/declined get fixed text).
    if env_ctx is not None:
        parts.append(env_ctx["sentence"])
        if env_ctx["citation"]:
            citations.append(env_ctx["citation"])

    # 2) KB anchor rule for the detected nutrient(s). With an approved
    #    envelope the anchor must be a rule that actually applies to this
    #    patient — a guideline rule that did not fire for the patient must
    #    never be cited as if it governed their plan.
    anchor = (
        _anchor_rule(kb, nutrients, role, applicability_patient)
        if nutrients
        else None
    )
    if anchor is not None:
        parts.append(_rule_sentence(anchor, role))
        parts.extend(_constraint_sentences(anchor, role, weight_kg)[:2])
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
                citations.append(hit["citation"])
            else:
                sentences = _dish_sentences([hit], role)
                parts.extend(sentences)

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