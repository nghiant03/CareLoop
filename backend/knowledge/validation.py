"""Validate executable knowledge shape, not the clinical accuracy of its sources."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from shared.envelope_schema import ConstraintKind, ExclusionKind, NutrientKind

NUTRIENTS = tuple(n.value for n in NutrientKind)
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_NUMERIC_FIELDS = {"age", "weight_kg", "bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL", "hba1c_pct"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")


def _number(value: Any, field: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{field} must be {'positive' if positive else 'nonnegative'}")


def _strings(value: Any, field: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{field} must be a {'nonempty ' if nonempty else ''}list")
    for item in value:
        _text(item, field)


def validate_documents(rules_document: dict, dishes: list[dict]) -> dict:
    """Reject unsupported DSL, duplicate IDs, incomplete nutrients and unsafe scope regressions.

    Missing optional guideline URLs/quotes and unverified catalogue values are
    disclosed, not silently upgraded. This is not source verification, clinical
    approval, or a complete rule-behaviour regression suite.
    """
    canonical_json([rules_document, dishes])
    if not isinstance(rules_document, dict) or rules_document.get("dsl_version") != "1.0":
        raise ValueError("rules document must declare supported dsl_version '1.0'")
    rules = rules_document.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a nonempty list")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be an object")  # noqa: TRY004
        for field in ("rule_id", "guideline", "section"):
            _text(rule.get(field), field)
        rid = rule["rule_id"]
        if not _IDENTIFIER.fullmatch(rid) or rid in ids:
            raise ValueError(f"invalid or duplicate rule_id: {rid}")
        ids.add(rid)
        priority = rule.get("priority")
        if type(priority) is not int or not 0 <= priority <= 10000:
            raise ValueError(f"{rid}: priority must be an integer in [0, 10000]")
        for field in ("url", "verbatim_quote", "notes"):
            if rule.get(field) is not None and not isinstance(rule[field], str):
                raise ValueError(f"{rid}: {field} must be a string or null")
        conditions, actions = rule.get("conditions"), rule.get("actions")
        if not isinstance(conditions, list) or not isinstance(actions, list) or not actions:
            raise ValueError(f"{rid}: conditions and nonempty actions must be lists")
        for condition in conditions:
            if not isinstance(condition, dict) or set(condition) != {"field", "op", "value"}:
                raise ValueError(f"{rid}: invalid condition shape")
            field, op, value = condition["field"], condition["op"], condition["value"]
            if field in {"diagnoses", "meds"} and op in {"in", "not_in"}:
                _strings(value, field, nonempty=True)
            elif field == "pregnant" and op == "eq" and type(value) is bool:
                pass
            elif field in _NUMERIC_FIELDS and op in {"ge", "gt", "le", "lt", "eq", "between"}:
                values = value if op == "between" else [value]
                if not isinstance(values, list) or (op == "between" and len(values) != 2):
                    raise ValueError(f"{rid}: between requires two bounds")
                for bound in values:
                    _number(bound, field)
                if op == "between" and values[0] > values[1]:
                    raise ValueError(f"{rid}: reversed bounds")
            else:
                raise ValueError(f"{rid}: unsupported condition {field!r}/{op!r}")
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError(f"{rid}: action must be an object")  # noqa: TRY004
            kind = action.get("type")
            if kind == "set_constraint":
                NutrientKind(action.get("nutrient"))
                ConstraintKind(action.get("kind"))
                _number(action.get("value"), "constraint value")
            elif kind == "exclude":
                ExclusionKind(action.get("kind"))
                _text(action.get("value"), "exclusion value")
                _text(action.get("reason"), "exclusion reason")
            elif kind in {"assert", "flag"}:
                _text(action.get("key"), "flag key")
                if not _IDENTIFIER.fullmatch(action["key"]) or "value" not in action:
                    raise ValueError(f"{rid}: invalid flag")
            else:
                raise ValueError(f"{rid}: unsupported action type {kind!r}")
    if not isinstance(dishes, list) or not dishes:
        raise ValueError("dishes must be a nonempty list")
    ids = set()
    for dish in dishes:
        if not isinstance(dish, dict):
            raise ValueError("each dish must be an object")  # noqa: TRY004
        for field in ("dish_id", "name", "category", "provenance"):
            _text(dish.get(field), field)
        if dish["dish_id"] in ids:
            raise ValueError(f"duplicate dish_id: {dish['dish_id']}")
        ids.add(dish["dish_id"])
        _number(dish.get("portion_g"), "portion_g", positive=True)
        for nutrient in NUTRIENTS:
            _number(dish.get(nutrient), nutrient)
        for field in ("tags", "ingredients"):
            _strings(dish.get(field), field)
        if type(dish.get("verified")) is not bool:
            raise ValueError("verified must be a boolean")
        if "price_sgd" in dish:
            _number(dish["price_sgd"], "price_sgd")
    from rules.engine import validate_rulebook

    validate_rulebook(rules)
    return {"rules": len(rules), "dishes": len(dishes),
            "unverified_dishes": sum(not dish["verified"] for dish in dishes),
            "rules_without_quote": sum(not rule.get("verbatim_quote") for rule in rules),
            "rules_without_url": sum(not rule.get("url") for rule in rules),
            "clinical_validation": "not_established"}
