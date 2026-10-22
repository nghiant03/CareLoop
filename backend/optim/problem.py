"""Canonical meal plan objectives and hard constraint evaluation."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    ExclusionKind,
    NutrientEnvelope,
)

from .exclusion_mapping import semantic_exclusion_hit
from .toy_data import NUTRIENT_KEYS, Dish

DAYS = 7
MEALS_PER_DAY = 3
SLOTS = DAYS * MEALS_PER_DAY
MEAL_LABELS = ("breakfast", "lunch", "dinner")

EPS = 1e-9

OBJECTIVE_NAMES: tuple[str, ...] = (
    "nutrient_target_deviation",
    "preference_fit",
    "variety",
    "cost",
)

# Placeholder preferences are not patient specific.
TAG_PREFERENCE: dict[str, float] = {
    "lean_protein": 1.0,
    "high_protein": 1.0,
    "vegetable": 1.0,
    "high_fiber": 0.8,
    "low_sodium": 0.8,
    "moderate_sodium": 0.0,
    "high_sodium": -1.0,
    "deep_fried": -1.2,
    "high_sat_fat": -1.0,
    "high_energy": -0.3,
}

# Raw deviation mixes nutrient units despite scaling.
SCALAR_WEIGHTS: dict[str, float] = {
    "nutrient_target_deviation": 0.001,
    "preference_fit": 0.5,
    "variety": 0.5,
    "cost": 0.02,
}


class EnvelopeNotApprovedError(RuntimeError):
    """Raised when a non-APPROVED envelope is handed to the optimiser."""


Plan = list[list[str]]


def dish_lookup(dishes: list[Dish]) -> dict[str, Dish]:
    return {d.dish_id: d for d in dishes}


def _day_dishes(plan: Plan, day: int) -> list[str]:
    out: list[str] = []
    for meal in plan[day * MEALS_PER_DAY : (day + 1) * MEALS_PER_DAY]:
        out.extend(meal)
    return out


def sum_nutrients(dish_ids: list[str], lookup: dict[str, Dish]) -> dict[str, float]:
    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    for did in dish_ids:
        dish = lookup.get(did)
        if dish is None:
            continue
        for key in NUTRIENT_KEYS:
            totals[key] += dish.nutrient(key)
    return totals


def daily_totals(plan: Plan, dishes: list[Dish]) -> list[dict[str, float]]:
    lookup = dish_lookup(dishes)
    n_days = len(plan) // MEALS_PER_DAY
    return [sum_nutrients(_day_dishes(plan, d), lookup) for d in range(n_days)]


def _require_approved(envelope: NutrientEnvelope) -> None:
    if getattr(envelope, "status", None) != EnvelopeStatus.APPROVED:
        raise EnvelopeNotApprovedError(
            "optimiser refuses non-APPROVED envelope "
            f"(status={getattr(envelope, 'status', None)!r}); "
            "only EnvelopeStatus.APPROVED may be consumed downstream"
        )


def _validate_plan(plan: Plan) -> int:
    if len(plan) % MEALS_PER_DAY != 0:
        raise ValueError(
            f"plan length {len(plan)} is not a multiple of MEALS_PER_DAY={MEALS_PER_DAY}"
        )
    return len(plan) // MEALS_PER_DAY


def _matches_exclusion(flag, dish: Dish) -> bool:
    value = flag.value.strip().lower()
    ingredients = {i.lower() for i in dish.ingredients}
    tags = {t.lower() for t in dish.tags}
    category = dish.category.lower()

    if flag.kind == ExclusionKind.INGREDIENT:
        return value in ingredients
    if flag.kind == ExclusionKind.DISH_CATEGORY:
        if value == category or value in tags:
            return True
        return semantic_exclusion_hit(flag.kind.value, value, dish)
    if flag.kind in (ExclusionKind.MACRO_PATTERN, ExclusionKind.DIET_PATTERN):
        if value in tags or value == category:
            return True
        return semantic_exclusion_hit(flag.kind.value, value, dish)
    return False


def exclusion_for(dish: Dish, envelope: NutrientEnvelope):
    for flag in envelope.exclusions:
        if _matches_exclusion(flag, dish):
            return flag
    return None


def allowed_dishes(envelope: NutrientEnvelope, dishes: list[Dish]) -> list[Dish]:
    return [d for d in dishes if exclusion_for(d, envelope) is None]


@dataclass(frozen=True)
class ConstraintSlot:
    kind: str
    scope: str
    nutrient: str
    day: int | None
    limit: float


def constraint_layout(envelope: NutrientEnvelope, n_days: int = DAYS) -> list[ConstraintSlot]:
    """Each MAX ceiling contributes daily slots followed by its horizon slot."""
    layout: list[ConstraintSlot] = []
    for c in envelope.targets:
        if c.kind == ConstraintKind.MAX:
            for day in range(n_days):
                layout.append(ConstraintSlot("max", "daily", c.nutrient.value, day, c.value))
            layout.append(ConstraintSlot("max", "horizon", c.nutrient.value, None, c.value * n_days))
    return layout


def constraint_names(envelope: NutrientEnvelope, n_days: int = DAYS) -> list[str]:
    return [
        f"{s.kind}:{s.scope}:{s.nutrient}"
        + (f":day{s.day}" if s.day is not None else "")
        for s in constraint_layout(envelope, n_days)
    ]


def constraint_vector(
    plan: Plan, envelope: NutrientEnvelope, dishes: list[Dish], n_days: int | None = None
) -> list[float]:
    """Excesses are unshifted. Pymoo adapters subtract EPS to match canonical tolerance."""
    _require_approved(envelope)
    n = _validate_plan(plan) if n_days is None else n_days
    lookup = dish_lookup(dishes)
    daily = [sum_nutrients(_day_dishes(plan, d), lookup) for d in range(n)]
    vec: list[float] = []
    for c in envelope.targets:
        if c.kind != ConstraintKind.MAX:
            continue
        key = c.nutrient.value
        for d in range(n):
            vec.append(max(0.0, daily[d][key] - c.value))
        horizon = sum(daily[d][key] for d in range(n))
        vec.append(max(0.0, horizon - c.value * n))
    return vec


def _obj_target_deviation(
    daily: list[dict[str, float]], envelope: NutrientEnvelope
) -> float:
    constraints = list(envelope.targets)
    if not constraints or not daily:
        return 0.0
    dev = 0.0
    for totals in daily:
        for c in constraints:
            value = totals[c.nutrient.value]
            if c.kind == ConstraintKind.TARGET:
                dev += abs(value - c.value)
            elif c.kind == ConstraintKind.MIN:
                dev += max(0.0, c.value - value)
            else:
                dev += max(0.0, value - c.value)
    return dev / len(daily)


def _obj_preference_fit(plan: Plan, lookup: dict[str, Dish]) -> float:
    dishes = [lookup[d] for meal in plan for d in meal if d in lookup]
    if not dishes:
        return 0.0
    total = sum(sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in dishes)
    return -total / len(dishes)


def _obj_variety(plan: Plan, lookup: dict[str, Dish]) -> float:
    ids = [d for meal in plan for d in meal if d in lookup]
    if not ids:
        return 0.0
    counts = Counter(ids)
    n = len(ids)
    probs = [c / n for c in counts.values()]
    entropy = -sum(p * math.log(p) for p in probs)
    denom = math.log(len(lookup)) if len(lookup) > 1 else 1.0
    norm_entropy = min(1.0, entropy / denom) if denom > 0 else 0.0
    distinct_ratio = len(counts) / min(len(lookup), n)
    score = 0.5 * norm_entropy + 0.5 * distinct_ratio
    return -score


def _obj_cost(plan: Plan, lookup: dict[str, Dish]) -> float:
    return sum(lookup[d].price_sgd for meal in plan for d in meal if d in lookup)


def scalar_score(objectives: dict[str, float]) -> float:
    return sum(SCALAR_WEIGHTS[k] * objectives[k] for k in OBJECTIVE_NAMES)


def objective_vector(objectives: dict[str, float]) -> tuple[float, ...]:
    return tuple(objectives[k] for k in OBJECTIVE_NAMES)


def evaluate(
    plan: Plan, envelope: NutrientEnvelope, dishes: list[Dish]
) -> tuple[dict[str, float], list[dict]]:
    """Hard feasibility is separate from adequacy and meal delivery. Nutrient days and structural meal indices are zero based."""
    _require_approved(envelope)
    n_days = _validate_plan(plan)
    lookup = dish_lookup(dishes)

    violations: list[dict] = []

    for meal_index, meal in enumerate(plan):
        for did in meal:
            dish = lookup.get(did)
            if dish is None:
                violations.append(
                    {
                        "type": "unknown_dish",
                        "dish_id": did,
                        "meal_index": meal_index,
                        "amount": float("inf"),
                        "detail": f"dish {did!r} is not in the meal pool",
                    }
                )
                continue
            flag = exclusion_for(dish, envelope)
            if flag is not None:
                violations.append(
                    {
                        "type": "exclusion",
                        "dish_id": did,
                        "exclusion_kind": flag.kind.value,
                        "exclusion_value": flag.value,
                        "meal_index": meal_index,
                        "amount": float("inf"),
                        "detail": f"dish {did!r} excluded by {flag.kind.value}={flag.value!r}",
                    }
                )

    daily = [sum_nutrients(_day_dishes(plan, d), lookup) for d in range(n_days)]
    layout = constraint_layout(envelope, n_days)
    vector = constraint_vector(plan, envelope, dishes, n_days=n_days)
    for slot, magnitude in zip(layout, vector):
        if magnitude <= EPS:
            continue
        key = slot.nutrient
        if slot.scope == "daily":
            actual = daily[slot.day][key]  # type: ignore[index]
        else:
            actual = sum(daily[d][key] for d in range(n_days))
        violations.append(
            {
                "type": f"{slot.kind}_{slot.scope}",
                "nutrient": key,
                "scope": slot.scope,
                "day": slot.day,
                "limit": slot.limit,
                "actual": actual,
                "amount": magnitude,
                "detail": (
                    f"{key} {slot.scope} total {actual:.3f} violates "
                    f"{slot.kind} {slot.limit:.3f}"
                ),
            }
        )

    objectives = {
        "nutrient_target_deviation": _obj_target_deviation(daily, envelope),
        "preference_fit": _obj_preference_fit(plan, lookup),
        "variety": _obj_variety(plan, lookup),
        "cost": _obj_cost(plan, lookup),
    }
    return objectives, violations


def is_feasible(plan: Plan, envelope: NutrientEnvelope, dishes: list[Dish]) -> bool:
    """An empty plan may be hard feasible. This check does not assess adequacy or meal delivery."""
    _require_approved(envelope)
    _objectives, violations = evaluate(plan, envelope, dishes)
    return len(violations) == 0


def violation_count(violations: list[dict]) -> int:
    return len(violations)


def violation_magnitude(violations: list[dict]) -> float:
    total = 0.0
    for v in violations:
        amount = v.get("amount", 0.0)
        total += 1e9 if amount == float("inf") else float(amount)
    return total


__all__ = [
    "DAYS",
    "EPS",
    "MEALS_PER_DAY",
    "MEAL_LABELS",
    "OBJECTIVE_NAMES",
    "SCALAR_WEIGHTS",
    "SLOTS",
    "TAG_PREFERENCE",
    "ConstraintSlot",
    "EnvelopeNotApprovedError",
    "Plan",
    "allowed_dishes",
    "constraint_layout",
    "constraint_names",
    "constraint_vector",
    "daily_totals",
    "dish_lookup",
    "evaluate",
    "exclusion_for",
    "is_feasible",
    "objective_vector",
    "scalar_score",
    "sum_nutrients",
    "violation_count",
    "violation_magnitude",
]
