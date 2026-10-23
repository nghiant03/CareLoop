from collections import defaultdict
from math import isfinite

NUMERIC_FACTS = {"age_years", "weight_kg", "height_cm", "egfr"}
BOOL_FACTS = {
    "pregnant",
    "breastfeeding",
    "dialysis",
    "vegetarian",
    "include_eggs",
    "include_dairy",
}
TEXT_FACTS = {"sex", "ckd_stage"}
LIST_FACTS = {"conditions", "medications", "allergies", "dislikes"}
UNITS = {
    "energy": "kcal/day",
    "protein": "g/day",
    "carbohydrate": "g/day",
    "fat": "g/day",
    "saturated_fat": "g/day",
    "fibre": "g/day",
    "free_sugars": "g/day",
    "sodium": "mg/day",
    "potassium": "mg/day",
    "phosphorus": "mg/day",
}


def predicate(condition, facts):
    """Return truth (None means unknown), missing facts, and unsupported expressions."""
    key, op, expected = condition["fact"], condition["operator"], condition["value"]
    numeric = isinstance(expected, (int, float)) and not isinstance(expected, bool)
    supported = (
        (key in NUMERIC_FACTS and op in {"eq", "gte", "lte"} and numeric)
        or (key in BOOL_FACTS and op == "eq" and isinstance(expected, bool))
        or (key in TEXT_FACTS and op == "eq" and isinstance(expected, str))
        or (key in LIST_FACTS and op == "contains" and isinstance(expected, str))
    )
    if not supported:
        return None, [], [f"Unsupported predicate: {key} {op} {expected!r}"]
    actual = facts.get(key)
    if actual is None:
        return None, [key], []
    if op == "gte":
        return actual >= expected, [], []
    if op == "lte":
        return actual <= expected, [], []
    if op == "contains":
        return expected in actual, [], []
    return actual == expected, [], []


def evaluate_rule(rule, facts):
    body = rule["body"]
    result = {
        "rule_id": str(rule["rule_id"]),
        "revision": rule["revision"],
        "citation": {key: body[key] for key in ("source_id", "quote", "location")},
        "source_action": body["action"],
        "action": None,
        "missing": [],
        "issues": [],
        "population_note": body["population_note"],
        "exception_note": body["exception_note"],
    }
    applicable = [predicate(p, facts) for p in body["applicability"]]
    exceptions = [predicate(p, facts) for p in body["exceptions"]]
    if any(truth is False for truth, _, _ in applicable):
        return {**result, "status": "not_applicable"}
    if any(truth is True for truth, _, _ in exceptions):
        return {**result, "status": "excluded"}
    for _, missing, issues in applicable + exceptions:
        result["missing"].extend(missing)
        result["issues"].extend(issues)
    result["missing"] = sorted(set(result["missing"]))
    if result["missing"] or result["issues"]:
        return {**result, "status": "incomplete"}
    action = dict(body["action"])
    if action["kind"] in {"assessment", "additional"}:
        return {
            **result,
            "status": "needs_clinician",
            "issues": [
                "Requires clinician assessment or an explicitly completed total; "
                "not an automatic target"
            ],
        }
    if action["kind"] in {"intake", "ceiling", "range"}:
        if action["subject"] == "protein" and action["unit"] == "g/kg/day":
            weight = facts.get("weight_kg")
            if weight is None:
                return {**result, "status": "incomplete", "missing": ["weight_kg"]}
            action["amount"] *= weight
            if action.get("upper") is not None:
                action["upper"] *= weight
            if not all(
                isfinite(value)
                for value in (action["amount"], action.get("upper"))
                if value is not None
            ):
                return {
                    **result,
                    "status": "needs_clinician",
                    "issues": ["Per-kg calculation exceeds supported numeric range"],
                }
            action["unit"] = "g/day"
            result["calculation"] = {"operation": "per_kg_times_weight", "weight_kg": weight}
        if UNITS.get(action["subject"]) != action["unit"]:
            return {
                **result,
                "status": "needs_clinician",
                "issues": [
                    "Unsupported nutrient or unit; provide a clinician-authored supported target"
                ],
            }
    return {**result, "status": "applicable", "action": action}


def evaluate(rules, facts):
    return [evaluate_rule(rule, facts) for rule in rules]


def signature(evaluation):
    return sorted(
        (r["rule_id"], r["revision"], r["status"])
        for r in evaluation
        if r["status"] not in {"not_applicable", "excluded"}
    )


def target_blockers(evaluation, items, dispositions):
    blockers = []
    disposed = {d["rule"]["rule_id"] for d in dispositions}
    selected = {item["rule"]["rule_id"] for item in items if item["origin"] == "evidence"}
    for result in evaluation:
        if result["missing"]:
            blockers.append({"rule_id": result["rule_id"], "missing": result["missing"]})
        elif result["status"] == "incomplete":
            blockers.append({"rule_id": result["rule_id"], "issues": result["issues"]})
        elif result["status"] in {"applicable", "needs_clinician"}:
            if result["rule_id"] not in selected | disposed:
                blockers.append(
                    {"rule_id": result["rule_id"], "issue": "Clinician disposition required"}
                )
    grouped = defaultdict(list)
    for item in items:
        action = item["action"]
        if action["kind"] in {"intake", "ceiling", "range"}:
            grouped[action["subject"]].append(action)
    for subject, actions in grouped.items():
        keys = {(a["kind"], a["amount"], a.get("upper"), a["unit"]) for a in actions}
        if len(keys) > 1:
            blockers.append(
                {"subject": subject, "issue": "Resolve competing numeric targets explicitly"}
            )
    if not items:
        blockers.append({"issue": "At least one completed target is required"})
    return blockers


def evidence_item(result):
    return {
        "origin": "evidence",
        "rule": {"rule_id": result["rule_id"], "revision": result["revision"]},
        "citation": result["citation"],
        "action": result["action"],
        "calculation": result.get("calculation"),
    }
