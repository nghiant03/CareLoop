"""Conservative structured overlap analysis, not free-text clinical interpretation."""

from collections import defaultdict

from careloop.patients.engine import BOOL_FACTS, LIST_FACTS, NUMERIC_FACTS, predicate


def overlap(left, right):
    constraints = defaultdict(list)
    for body in (left, right):
        for field, negated in (("applicability", False), ("exceptions", True)):
            for p in body[field]:
                if predicate(p, {})[2]:
                    return None
                constraints[p["fact"]].append((p["operator"], p["value"], negated))
    for fact, conditions in constraints.items():
        if fact in NUMERIC_FACTS:
            lower, upper, lower_closed, upper_closed = float("-inf"), float("inf"), True, True
            excluded = set()
            for op, value, negated in conditions:
                if op == "eq" and negated:
                    excluded.add(value)
                    continue
                low = op in {"eq", "gte"} if not negated else op == "lte"
                high = op in {"eq", "lte"} if not negated else op == "gte"
                if low and value >= lower:
                    lower_closed = not negated and (lower_closed if value == lower else True)
                    lower = value
                if high and value <= upper:
                    upper_closed = not negated and (upper_closed if value == upper else True)
                    upper = value
            if lower > upper or (
                lower == upper and (not lower_closed or not upper_closed or lower in excluded)
            ):
                return False
        else:
            required = {value for _, value, negated in conditions if not negated}
            excluded = {value for _, value, negated in conditions if negated}
            if required & excluded:
                return False
            if fact not in LIST_FACTS and len(required) > 1:
                return False
            if fact in BOOL_FACTS and excluded == {True, False}:
                return False
    return True


def bounds(action):
    if action["kind"] == "ceiling":
        return 0, action["amount"]
    if action["kind"] == "range":
        return action["amount"], action["upper"]
    return None


def signature(action):
    return tuple(action.get(k) for k in ("kind", "unit", "amount", "upper"))


def analyse(rows, selected_ids):
    blocking, review = [], []
    seen = set()
    pairs = (
        (left, right)
        for left in rows
        if str(left["rule_id"]) in selected_ids
        for right in rows
        if left["rule_id"] != right["rule_id"]
    )
    for left, right in pairs:
        key = tuple(sorted((str(left["rule_id"]), str(right["rule_id"]))))
        if key in seen:
            continue
        seen.add(key)
        a, b = left["body"]["action"], right["body"]["action"]
        if a["subject"] != b["subject"]:
            continue
        common = overlap(left["body"], right["body"])
        if common is False:
            continue
        if signature(a) == signature(b) and a["kind"] in {"range", "ceiling", "intake"}:
            continue
        finding = {
            "rules": [
                {"rule_id": str(row["rule_id"]), "revision": row["revision"]}
                for row in (left, right)
            ],
            "subject": a["subject"],
            "applicability_overlap": common,
            "citations": [
                {key: row["body"][key] for key in ("source_id", "location", "quote")}
                for row in (left, right)
            ],
        }
        x, y = bounds(a), bounds(b)
        if (
            common is True
            and x
            and y
            and a["unit"] == b["unit"]
            and max(x[0], y[0]) > min(x[1], y[1])
        ):
            blocking.append(
                {**finding, "issue": "Overlapping populations have incompatible numeric bounds"}
            )
        else:
            review.append(
                {**finding, "issue": "Different guidance needs explicit reviewer interpretation"}
            )
    return {
        "blocking_conflicts": blocking,
        "review_findings": review,
        "scope": "Supported structured predicates and same-unit numeric bounds only",
        "manual_review_required": True,
    }
