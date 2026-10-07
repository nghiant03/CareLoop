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
   can be cited for the question, the answer is refused instead.
5. **Low-confidence refusal** — if no nutrient is detected and the best
   retrieval score is below ``retrieval.MIN_SCORE``, refuse and suggest
   speaking with a clinician.

Envelope handling honours the approval gate (``core/approval_gate.py``):
an APPROVED envelope's numbers are served as clinician-approved; a PROPOSED
(or EDITED/REJECTED) envelope is still surfaced for transparency but the
answer explicitly notes it has not been approved yet.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.app.chat import escalation, retrieval
from backend.app.kb.graph_store import KBGraph
from backend.app.chat.llm import LLMAdapter

__all__ = ["answer", "detect_nutrients", "format_value", "MAX_ANSWER_CHUNKS"]

MAX_ANSWER_CHUNKS = 3

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


def _anchor_rule(kb: KBGraph, nutrients: list[str]) -> Optional[dict[str, Any]]:
    """Highest-priority current KB rule covering the detected nutrients.

    ``rules_for_nutrient`` already sorts by priority DESC then rule_id, so the
    choice is deterministic (CKD rules outrank DASH/ADA/generic, and
    ``CKD-2024-*`` sorts before ``CONFLICT-*`` on ties).
    """
    for nutrient in nutrients:
        rules = kb.rules_for_nutrient(nutrient)
        if rules:
            return rules[0]
    return None


def _envelope_context(envelope: Optional[dict[str, Any]], nutrients: list[str]) -> Optional[dict[str, Any]]:
    if not envelope:
        return None
    status = str(envelope.get("status", ""))
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
    amount = format_value(target.get("value"), target.get("unit", ""))
    kind = target.get("kind", "")
    if kind == "max":
        core = f"a daily {label} limit of {amount}"
    elif kind == "min":
        core = f"a daily {label} minimum of {amount}"
    else:
        core = f"a daily {label} target of {amount}"

    approved = status == "APPROVED"
    if approved:
        sentence = f"Your clinician-approved plan sets {core}."
    else:
        sentence = (
            f"Your current plan sets {core}, but note it is {status} and has "
            f"not been approved by your clinician yet."
        )

    citation = None
    for fired in envelope.get("fired_rules") or []:
        summary = str(fired.get("action_summary", "")).lower()
        if nutrient.split("_")[0] in summary or nutrient in summary:
            citation = fired.get("citation")
            break
    if citation is None:
        for cit in envelope.get("citations") or []:
            citation = cit
            break
    return {
        "envelope_id": envelope.get("envelope_id"),
        "status": status,
        "approved": approved,
        "sentence": sentence,
        "citation": citation,
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


def _constraint_sentences(rule: dict[str, Any], role: str) -> list[str]:
    sentences = []
    for constraint in rule.get("constraints", []):
        label = _PLAIN_LABELS.get(constraint.get("nutrient"), constraint.get("nutrient"))
        amount = format_value(constraint.get("value"), constraint.get("unit", ""))
        phrase = _kind_phrase(constraint.get("kind", ""))
        prefix = f"[{rule['rule_id']}] " if role == "clinician" else ""
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


def answer(
    question: str,
    kb: KBGraph,
    envelope: Optional[dict[str, Any]] = None,
    role: str = "patient",
    llm: Optional[LLMAdapter] = None,
) -> dict[str, Any]:
    """Grounded, deterministic answer with mandatory citations.

    Returns a dict with keys: ``status`` (``answered`` | ``refused`` |
    ``escalated``), ``answer``, ``citations``, ``envelope``, ``retrieval`` and
    ``role``. ``role="clinician"`` keeps rule ids inline in the text; the
    patient view hides them from the prose (they remain in ``citations``).
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

    hits = retrieval.build_index(kb).retrieve(question, k=5)
    best_score = hits[0]["score"] if hits else 0.0
    nutrients = detect_nutrients(question)
    # The envelope is only consulted when the question is actually about the
    # patient's nutrition (detected nutrient or a relevant KB hit) — an
    # unrelated question must be refused, not answered from plan numbers.
    relevant = bool(nutrients) or best_score > retrieval.MIN_SCORE
    env_ctx = _envelope_context(envelope, nutrients) if relevant else None

    parts: list[str] = []
    citations: list[dict[str, Any]] = []

    # 1) Envelope numbers (approved vs not-yet-approved note).
    if env_ctx is not None:
        parts.append(env_ctx["sentence"])
        if env_ctx["citation"]:
            citations.append(env_ctx["citation"])

    # 2) KB anchor rule for the detected nutrient(s).
    anchor = _anchor_rule(kb, nutrients) if nutrients else None
    if anchor is not None:
        parts.append(_rule_sentence(anchor, role))
        parts.extend(_constraint_sentences(anchor, role)[:2])
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