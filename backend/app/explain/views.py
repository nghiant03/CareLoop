"""Explanation view builders (implementation).

Deterministic and pure: same inputs always produce the same dict, no I/O, no
clock, no randomness.
"""

from __future__ import annotations

import re
from typing import Any, Optional

__all__ = ["clinician_explanation", "patient_explanation"]

# Patient-facing nutrient labels; _NUTRIENT_ORDER controls display order.
_PLAIN_LABELS = {
    "sodium_mg": "sodium",
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

_NUTRIENT_ORDER = [
    "energy_kcal", "protein_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
    "carbs_g", "fiber_g", "sat_fat_g", "fat_g", "sugar_g",
]

# Nutrient detection in fired-rule action summaries (for priority overlaps
# and constraint→rule citation matching). Handles both the hand-worked trace
# style ("Na ceiling = 2000 mg/d") and the engine style ("set sodium_mg max =
# 2000 mg/d") — patterns match into suffixed tokens like ``sodium_mg``.
_NUTRIENT_SUMMARY_PATTERNS = {
    "sodium_mg": re.compile(r"sodium|\bna\b", re.IGNORECASE),
    "potassium_mg": re.compile(r"potassium|\bk\b", re.IGNORECASE),
    "phosphorus_mg": re.compile(r"phosphorus|phosphate|po4", re.IGNORECASE),
    "protein_g": re.compile(r"protein", re.IGNORECASE),
    "energy_kcal": re.compile(r"energy|\bkcal\b|calorie", re.IGNORECASE),
    "fiber_g": re.compile(r"fib(er|re)", re.IGNORECASE),
    "sat_fat_g": re.compile(r"sat[\s_.,]?fat|saturated|satfat", re.IGNORECASE),
    "carbs_g": re.compile(r"carb", re.IGNORECASE),
    "fat_g": re.compile(r"\bfat", re.IGNORECASE),
    "sugar_g": re.compile(r"\bsugar", re.IGNORECASE),
}


def _nutrients_in_text(text: str) -> list[str]:
    lowered = str(text or "").lower()
    found = [
        nutrient
        for nutrient in _NUTRIENT_ORDER
        if _NUTRIENT_SUMMARY_PATTERNS[nutrient].search(lowered)
    ]
    # "saturated fat" mentions must not be misread as total-fat constraints.
    if "sat_fat_g" in found and "fat_g" in found:
        found.remove("fat_g")
    return found

_CONFLICT_PREFIX = "CONFLICT"

_PLAIN_AVOID = {
    "potassium_chloride": "potassium-based salt substitutes",
    "high_potassium_foods": "high-potassium foods (such as bananas, oranges, potatoes and tomatoes)",
    "phosphate_additive_processed": "processed foods with phosphate additives (such as processed meats and colas)",
    "sugar_sweetened_beverage": "sugar-sweetened drinks",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _format_amount(value: Any, unit: str) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return f"{value} {unit}".strip()
    if unit == "mg" and num >= 1000:
        grams = num / 1000.0
        text = f"{grams:.1f}".rstrip("0").rstrip(".")
        return f"{text} g"
    if num == int(num):
        return f"{int(num)} {unit}".strip()
    return f"{num:g} {unit}".strip()


def _citations_of(fired: dict[str, Any]) -> dict[str, Any]:
    citation = fired.get("citation") or {}
    return {
        "rule_id": citation.get("rule_id") or fired.get("rule_id"),
        "guideline": citation.get("guideline"),
        "section": citation.get("section"),
        "url": citation.get("url"),
        "verbatim_quote": citation.get("verbatim_quote"),
    }


def _rule_citation_for_nutrient(
    fired_rules: list[dict[str, Any]], nutrient: str
) -> Optional[dict[str, Any]]:
    """Choose a citation from nutrient mentions, not exact constraint provenance.

    Prefer summaries not starting with exclude/assert, then higher priority and
    lower rule ID. Ignore CONFLICT rules; return None without a matching mention.
    """
    candidates = []
    for fired in fired_rules:
        if str(fired.get("rule_id", "")).startswith(_CONFLICT_PREFIX):
            continue
        if nutrient in _nutrients_in_text(fired.get("action_summary", "")):
            candidates.append(fired)
    if not candidates:
        return None

    def sort_key(fired: dict[str, Any]) -> tuple:
        summary = str(fired.get("action_summary", "")).strip().lower()
        mentions_only = summary.startswith(("exclude", "assert"))
        return (1 if mentions_only else 0, -int(fired.get("priority", 0)), str(fired.get("rule_id", "")))

    candidates.sort(key=sort_key)
    return _citations_of(candidates[0])


# ---------------------------------------------------------------------------
# Clinician view
# ---------------------------------------------------------------------------


def clinician_explanation(envelope: dict, trace: list[dict]) -> dict:
    """Structured clinician/audit explanation of an envelope.

    ``envelope`` is the NutrientEnvelope dict; ``trace`` is the RuleFire list
    (same shapes as ``rules/example_trace.json``). Returns:

    * ``fired_rules`` — id, priority, guideline link, patient/action summary;
    * ``conflicts_resolved`` — resolutions explicitly recorded by CONFLICT rules;
    * ``priority_overlaps`` — inferred nutrient mentions ordered by priority,
      not evidence of a constraint being overridden;
    * ``constraints`` — resulting targets with per-constraint citations;
    * ``exclusions`` — hard exclusions with citations.
    """
    fired_rules = [dict(f) for f in (trace or [])]

    fired_view = sorted(
        (
            {
                "rule_id": f.get("rule_id"),
                "priority": f.get("priority", 0),
                "guideline": (f.get("citation") or {}).get("guideline"),
                "section": (f.get("citation") or {}).get("section"),
                "url": (f.get("citation") or {}).get("url"),
                "verbatim_quote": (f.get("citation") or {}).get("verbatim_quote"),
                "patient_summary": f.get("patient_summary"),
                "action_summary": f.get("action_summary"),
            }
            for f in fired_rules
        ),
        key=lambda f: (-int(f["priority"]), str(f["rule_id"])),
    )

    conflicts: list[dict[str, Any]] = []

    # 1) Resolutions explicitly recorded by CONFLICT-* rules in the trace.
    for fired in fired_rules:
        if str(fired.get("rule_id", "")).startswith(_CONFLICT_PREFIX):
            conflicts.append(
                {
                    "recorded_by": fired.get("rule_id"),
                    "resolution": fired.get("action_summary"),
                    "priority": fired.get("priority", 0),
                }
            )

    # Nutrient mentions can overlap without conflicting (e.g. independent MIN/MAX).
    # Keep this display heuristic separate from recorded engine resolutions.
    priority_overlaps: list[dict[str, Any]] = []
    by_nutrient: dict[str, list[dict[str, Any]]] = {}
    for fired in fired_rules:
        if str(fired.get("rule_id", "")).startswith(_CONFLICT_PREFIX):
            continue
        for nutrient in _nutrients_in_text(fired.get("action_summary", "")):
            by_nutrient.setdefault(nutrient, []).append(fired)

    for nutrient in _NUTRIENT_ORDER:
        candidates = by_nutrient.get(nutrient, [])
        if len(candidates) < 2:
            continue
        candidates.sort(key=lambda f: (-int(f.get("priority", 0)), str(f.get("rule_id", ""))))
        winner = candidates[0]
        overridden = [
            {"rule_id": f.get("rule_id"), "priority": f.get("priority", 0)}
            for f in candidates[1:]
            if int(f.get("priority", 0)) < int(winner.get("priority", 0))
        ]
        if overridden:
            priority_overlaps.append(
                {
                    "nutrient": nutrient,
                    "highest_priority_rule_id": winner.get("rule_id"),
                    "highest_priority": winner.get("priority", 0),
                    "lower_priority_mentions": overridden,
                    "summary": (
                        f"{winner.get('rule_id')} (priority "
                        f"{winner.get('priority', 0)}) has higher priority than "
                        f"{', '.join(o['rule_id'] for o in overridden)} on "
                        f"{nutrient}"
                    ),
                }
            )

    constraints = []
    from shared.provenance import citation_for

    for target in envelope.get("targets") or []:
        nutrient = target.get("nutrient")
        constraints.append(
            {
                "nutrient": nutrient,
                "kind": target.get("kind"),
                "value": target.get("value"),
                "unit": target.get("unit"),
                "citation": (target.get("provenance") or {}).get("citation") or citation_for(target, fired_rules),
                "provenance": target.get("provenance"),
            }
        )

    exclusions = [
        {
            "kind": x.get("kind"),
            "value": x.get("value"),
            "reason": x.get("reason"),
            "citation": x.get("citation"),
        }
        for x in envelope.get("exclusions") or []
    ]

    return {
        "envelope_id": envelope.get("envelope_id"),
        "patient_id": envelope.get("patient_id"),
        "status": envelope.get("status"),
        "version": envelope.get("version"),
        "priority_basis": envelope.get("priority_basis"),
        "fired_rules": fired_view,
        "conflicts_resolved": conflicts,
        "priority_overlaps": priority_overlaps,
        "constraints": constraints,
        "exclusions": exclusions,
    }


# ---------------------------------------------------------------------------
# Patient view
# ---------------------------------------------------------------------------


def _target_phrases(targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One plain-language line per nutrient, merging min+max into a range."""
    grouped: dict[str, dict[str, Any]] = {}
    for target in targets:
        nutrient = target.get("nutrient")
        grouped.setdefault(nutrient, {})[target.get("kind")] = target

    lines = []
    for nutrient in _NUTRIENT_ORDER:
        if nutrient not in grouped:
            continue
        kinds = grouped[nutrient]
        label = _PLAIN_LABELS.get(nutrient, nutrient)
        unit = next(iter(kinds.values())).get("unit", "")
        if "min" in kinds and "max" in kinds:
            lo = _format_amount(kinds["min"]["value"], unit)
            hi = _format_amount(kinds["max"]["value"], unit)
            text = f"Aim for {lo} to {hi} of {label} a day"
        elif "max" in kinds:
            amount = _format_amount(kinds["max"]["value"], unit)
            text = f"Keep {label} under {amount} a day"
        elif "min" in kinds:
            amount = _format_amount(kinds["min"]["value"], unit)
            text = f"Get at least {amount} of {label} a day"
        else:
            target = kinds.get("target")
            amount = _format_amount(target["value"], unit) if target else ""
            text = f"Aim for about {amount} of {label} a day"
        lines.append(
            {
                "nutrient": nutrient,
                "label": label,
                "text": text + ".",
            }
        )
    return lines


def patient_explanation(envelope: dict, plan: Optional[dict] = None) -> dict:
    """Plain-language patient view of an envelope.

    Daily targets in "keep sodium under 2 g a day" style, short why-bullets
    drawn from the trace citations carried on the envelope, and simple
    avoid-choices. Rule ids and jargon stay out of the prose.
    """
    targets = list(envelope.get("targets") or [])
    fired_rules = list(envelope.get("fired_rules") or [])

    daily_targets = [
        {"label": line["label"], "text": line["text"]}
        for line in _target_phrases(targets)
    ]

    why = []
    for line in _target_phrases(targets):
        nutrient = line["nutrient"]
        citation = _rule_citation_for_nutrient(fired_rules, nutrient)
        if not citation:
            continue
        guideline = citation.get("guideline") or "your care team"
        why.append(f"{guideline} recommends: {line['text'].lower()}")

    avoid = []
    for exclusion in envelope.get("exclusions") or []:
        value = exclusion.get("value", "")
        avoid.append(_PLAIN_AVOID.get(value, str(value).replace("_", " ")))

    approval_note = None
    if envelope.get("status") != "APPROVED":
        approval_note = (
            "This plan is a proposal and has not been approved by your "
            "clinician yet."
        )

    plan_summary = None
    if isinstance(plan, dict):
        totals = plan.get("totals") or {}
        lines = []
        grouped: dict[str, dict[str, Any]] = {}
        for target in targets:
            grouped.setdefault(target.get("nutrient"), {})[target.get("kind")] = target
        for nutrient in _NUTRIENT_ORDER:
            if nutrient not in totals or nutrient not in grouped:
                continue
            kinds = grouped[nutrient]
            unit = next(iter(kinds.values())).get("unit", "")
            label = _PLAIN_LABELS.get(nutrient, nutrient)
            got = _format_amount(totals[nutrient], unit)
            if "max" in kinds:
                limit = _format_amount(kinds["max"]["value"], unit)
                lines.append(f"Today's meals: {got} of {label} out of your {limit} limit.")
            elif "min" in kinds:
                floor = _format_amount(kinds["min"]["value"], unit)
                lines.append(f"Today's meals: {got} of {label} towards your {floor} goal.")
            else:
                lines.append(f"Today's meals: {got} of {label}.")
        if lines:
            plan_summary = lines

    return {
        "headline": "Your daily nutrition targets",
        "daily_targets": daily_targets,
        "avoid": avoid,
        "why": why,
        "approval_note": approval_note,
        "plan_summary": plan_summary,
    }
