from __future__ import annotations

import re
from typing import Any

from shared.provenance import citation_for

__all__ = ["clinician_explanation", "patient_explanation"]

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
    lowered = (text or "").lower()
    found = [
        nutrient
        for nutrient in _NUTRIENT_ORDER
        if _NUTRIENT_SUMMARY_PATTERNS[nutrient].search(lowered)
    ]
    if "sat_fat_g" in found and "fat_g" in found:
        found.remove("fat_g")
    return found

_CONFLICT_PREFIX = "CONFLICT"

_CLINICIAN_EDIT_RULE_ID = "CLINICIAN-EDIT"

_PLAIN_AVOID = {
    "potassium_chloride": "potassium-based salt substitutes",
    "high_potassium_foods": "high-potassium foods (such as bananas, oranges, potatoes and tomatoes)",
    "phosphate_additive_processed": "processed foods with phosphate additives (such as processed meats and colas)",
    "sugar_sweetened_beverage": "sugar-sweetened drinks",
}


def _format_amount(value: Any, unit: str) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return f"{value} {unit}".strip()
    if unit == "mg" and num >= 1000 and num % 10 == 0:
        grams = num / 1000.0
        text = f"{grams:.2f}".rstrip("0").rstrip(".")
        return f"{text} g"
    if num == int(num):
        return f"{int(num)} {unit}".strip()
    return f"{num} {unit}".strip()


def _target_citation(
    target: dict[str, Any], fired_rules: list[dict[str, Any]]
) -> dict[str, Any] | None:
    provenance = target.get("provenance")
    if provenance:
        # Stale explicit provenance cannot borrow a matching legacy citation.
        if any(provenance.get(key) != target.get(key) for key in ("nutrient", "kind", "value", "unit")):
            return None
        return provenance.get("citation")
    return citation_for(target, fired_rules)


def clinician_explanation(envelope: dict, trace: list[dict]) -> dict:
    """Mention overlap is display metadata rather than evidence of a resolved conflict."""
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

    for fired in fired_rules:
        if str(fired.get("rule_id", "")).startswith(_CONFLICT_PREFIX):
            conflicts.append(
                {
                    "recorded_by": fired.get("rule_id"),
                    "resolution": fired.get("action_summary"),
                    "priority": fired.get("priority", 0),
                }
            )

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
        top_mention = candidates[0]
        lower_mentions = [
            {"rule_id": f.get("rule_id"), "priority": f.get("priority", 0)}
            for f in candidates[1:]
            if int(f.get("priority", 0)) < int(top_mention.get("priority", 0))
        ]
        if lower_mentions:
            priority_overlaps.append(
                {
                    "nutrient": nutrient,
                    "highest_priority_rule_id": top_mention.get("rule_id"),
                    "highest_priority": top_mention.get("priority", 0),
                    "lower_priority_mentions": lower_mentions,
                    "summary": (
                        f"{top_mention.get('rule_id')} (priority "
                        f"{top_mention.get('priority', 0)}) has higher priority than "
                        f"{', '.join(str(o['rule_id']) for o in lower_mentions)} on "
                        f"{nutrient}"
                    ),
                }
            )

    constraints = []
    for target in envelope.get("targets") or []:
        nutrient = target.get("nutrient")
        constraints.append(
            {
                "nutrient": nutrient,
                "kind": target.get("kind"),
                "value": target.get("value"),
                "unit": target.get("unit"),
                "citation": _target_citation(target, fired_rules),
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


def _target_phrases(targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, Any]] = {}
    for target in targets:
        nutrient = target.get("nutrient")
        if not isinstance(nutrient, str):
            continue
        grouped.setdefault(nutrient, {})[target.get("kind") or ""] = target

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


def patient_explanation(envelope: dict, plan: dict | None = None) -> dict:
    """Callers must gate personal guidance because unapproved inputs still expose target numbers."""
    targets = list(envelope.get("targets") or [])
    fired_rules = list(envelope.get("fired_rules") or [])
    grouped: dict[str, dict[str, Any]] = {}
    for target in targets:
        grouped.setdefault(target.get("nutrient"), {})[target.get("kind")] = target

    daily_targets = [
        {"label": line["label"], "text": line["text"]}
        for line in _target_phrases(targets)
    ]

    why = []
    for nutrient in _NUTRIENT_ORDER:
        source_groups: list[tuple[dict, list[dict]]] = []
        for target in grouped.get(nutrient, {}).values():
            citation = _target_citation(target, fired_rules)
            if not citation:
                continue
            for source, source_targets in source_groups:
                if source == citation:
                    source_targets.append(target)
                    break
            else:
                source_groups.append((citation, [target]))
        # Merge bounds only when both have the same authoring source.
        for citation, source_targets in source_groups:
            line = _target_phrases(source_targets)[0]
            if citation.get("rule_id") == _CLINICIAN_EDIT_RULE_ID:
                why.append(f"Your care team set: {line['text'].lower()}")
            elif citation.get("guideline"):
                why.append(f"{citation['guideline']} recommends: {line['text'].lower()}")

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
