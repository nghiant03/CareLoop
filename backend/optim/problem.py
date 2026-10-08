"""Formal multi-objective meal-plan optimisation problem (CareLoop, Module 4).

Decision variables
------------------
A plan is a flat list of ``n_days * MEALS_PER_DAY`` meal slots (day-major):
``plan[day * MEALS_PER_DAY + meal_index]`` is a list of dish ids served in that
meal.  The toy spike uses one dish per meal, but the formulation and every
objective/constraint below supports multi-dish meals.

Objectives (all minimised)
--------------------------
1. ``nutrient_target_deviation`` : mean over days of the deviation from the
   envelope's nutrient band — ``|total - target|`` for ``TARGET`` values,
   shortfall ``max(0, min - total)`` for ``MIN`` floors, and excess
   ``max(0, total - max)`` for ``MAX`` ceilings (zero for hard-feasible plans,
   kept as a smooth penalty that helps the search).
2. ``preference_fit``            : negative mean tag-preference score
   (placeholder weighting; Week 2 replaces with learned/patient prefs).
3. ``variety``                   : negative (normalised Shannon entropy +
   distinct-dish ratio) across the whole horizon.
4. ``cost``                      : sum of ``Dish.price_sgd`` across the plan.

Hard constraints
----------------
Per PLAN.md module 4 ("objectives = nutrient-target deviation, preference fit,
variety, cost; hard constraints = approved ceilings/exclusions"):

* ``ConstraintKind.MAX`` : daily total <= value for every day, and horizon total
  <= ``value * n_days``.
* ``ExclusionFlag``      : a dish is unusable if any ingredient / category / tag
  matches literally, or if a documented semantic mapping applies
  (``exclusion_mapping.py`` bridges rulebook values like
  ``high_potassium_foods`` to per-serving nutrient thresholds).
* membership            : every dish id must exist in the supplied dish pool.
* gate                  : only ``EnvelopeStatus.APPROVED`` envelopes may be used.

MIN floors and ``ConstraintKind.TARGET`` values are **soft**: they steer
``nutrient_target_deviation`` but never count as violations and never cause
infeasibility, so guideline floors (fibre, potassium, energy) guide the search
instead of making envelopes unsolvable.

All hard-constraint checks use a small epsilon so float noise never registers as
a violation.  The canonical invariant: the optimiser NEVER violates a MAX
constraint; infeasible candidates are rejected by :func:`is_feasible` and
penalised (constraint-dominance) by the search.
"""

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

from .toy_data import NUTRIENT_KEYS, Dish

from .exclusion_mapping import semantic_exclusion_hit

# ---------------------------------------------------------------------------
# Problem geometry
# ---------------------------------------------------------------------------
DAYS = 7
MEALS_PER_DAY = 3
SLOTS = DAYS * MEALS_PER_DAY
MEAL_LABELS = ("breakfast", "lunch", "dinner")

EPS = 1e-9

# Objective order is stable: objective vectors, CSV columns and pymoo F columns
# all follow this list.
OBJECTIVE_NAMES: tuple[str, ...] = (
    "nutrient_target_deviation",
    "preference_fit",
    "variety",
    "cost",
)

# Placeholder tag preferences (higher = more preferred). Used by
# preference_fit and by the greedy baseline. Week 2: derive from patient prefs.
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

# Placeholder scalarisation weights for picking a single "best" plan from a
# Pareto front (and for tie-breaking baselines). nutrient_target_deviation is
# divided by ~a daily energy scale so the four terms are comparable.
SCALAR_WEIGHTS: dict[str, float] = {
    "nutrient_target_deviation": 0.001,
    "preference_fit": 0.5,
    "variety": 0.5,
    "cost": 0.02,
}


class EnvelopeNotApprovedError(RuntimeError):
    """Raised when a non-APPROVED envelope is handed to the optimiser."""


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------
def _matches_exclusion(flag, dish: Dish) -> bool:
    value = flag.value.strip().lower()
    ingredients = {i.lower() for i in dish.ingredients}
    tags = {t.lower() for t in dish.tags}
    category = dish.category.lower()

    if flag.kind == ExclusionKind.INGREDIENT:
        return value in ingredients
    if flag.kind == ExclusionKind.DISH_CATEGORY:
        # Match either the category field or a category-like tag, so toy and
        # Week-2 data both work; fall back to the documented semantic mapping
        # for rulebook values that no dataset tag spells out (e.g.
        # ``high_potassium_foods`` -> potassium per serving > 500 mg).
        if value == category or value in tags:
            return True
        return semantic_exclusion_hit(flag.kind.value, value, dish)
    if flag.kind in (ExclusionKind.MACRO_PATTERN, ExclusionKind.DIET_PATTERN):
        if value in tags or value == category:
            return True
        return semantic_exclusion_hit(flag.kind.value, value, dish)
    return False


def exclusion_for(dish: Dish, envelope: NutrientEnvelope):
    """Return the first exclusion flag hitting ``dish``, or ``None``."""
    for flag in envelope.exclusions:
        if _matches_exclusion(flag, dish):
            return flag
    return None


def allowed_dishes(envelope: NutrientEnvelope, dishes: list[Dish]) -> list[Dish]:
    """Dishes that survive every exclusion flag (the runnable meal pool)."""
    return [d for d in dishes if exclusion_for(d, envelope) is None]


# ---------------------------------------------------------------------------
# Constraint vector (fixed length; used by pymoo and by evaluate)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConstraintSlot:
    kind: str  # "max" | "min"
    scope: str  # "daily" | "horizon"
    nutrient: str
    day: int | None
    limit: float


def constraint_layout(envelope: NutrientEnvelope, n_days: int = DAYS) -> list[ConstraintSlot]:
    """Canonical, fixed-length ordering of the HARD nutrient constraints.

    Only ``MAX`` ceilings are hard (per PLAN.md module 4): one daily slot per
    day plus one horizon slot per MAX constraint.  ``MIN`` floors and
    ``TARGET`` values are soft objective terms (see
    :func:`_obj_target_deviation`) and deliberately absent here, so guideline
    floors never make an envelope unsolvable.
    """
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
    """Non-negative violation magnitudes (0 == satisfied) in canonical order.

    Fixed length for a given envelope and horizon, so it can be fed directly to
    pymoo as ``G`` (``G <= 0`` means satisfied).  HARD constraints only: MAX
    ceilings (daily + horizon).  MIN floors and TARGETs are soft and never
    appear in the constraint vector.
    """
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


# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------
def _obj_target_deviation(
    daily: list[dict[str, float]], envelope: NutrientEnvelope
) -> float:
    """Mean per-day deviation from the envelope's nutrient band (soft term).

    ``TARGET`` -> ``|total - target|``; ``MIN`` -> shortfall
    ``max(0, min - total)``; ``MAX`` -> excess ``max(0, total - max)`` (zero for
    hard-feasible plans; kept so the search keeps a gradient inside the
    infeasible region).  Guideline floors therefore *guide* the search without
    ever counting as violations.
    """
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
            else:  # MAX
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
    """Lower is better: weighted sum used to pick one plan from a front."""
    return sum(SCALAR_WEIGHTS[k] * objectives[k] for k in OBJECTIVE_NAMES)


def objective_vector(objectives: dict[str, float]) -> tuple[float, ...]:
    return tuple(objectives[k] for k in OBJECTIVE_NAMES)


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------
def evaluate(
    plan: Plan, envelope: NutrientEnvelope, dishes: list[Dish]
) -> tuple[dict[str, float], list[dict]]:
    """Return ``(objectives, constraint_violations)`` for ``plan``.

    ``objectives`` is a dict keyed by :data:`OBJECTIVE_NAMES` (all minimise).
    ``constraint_violations`` lists HARD violations only — MAX ceilings
    (daily + horizon), exclusions and membership.  MIN shortfalls and TARGET
    deviations are soft objective terms and never appear here.  An empty list
    means feasible.  Raises :class:`EnvelopeNotApprovedError` for non-APPROVED
    envelopes.
    """
    _require_approved(envelope)
    n_days = _validate_plan(plan)
    lookup = dish_lookup(dishes)

    violations: list[dict] = []

    # membership + exclusion (hard, structural)
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

    # nutrient hard constraints (MAX daily + horizon; MIN floors are soft)
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
    """True iff ``plan`` violates no HARD constraint (MAX ceiling / exclusion).

    MIN floors and TARGET values are soft objective terms and never affect
    feasibility (see the module docstring for the PLAN.md module-4 encoding).
    """
    _require_approved(envelope)
    _objectives, violations = evaluate(plan, envelope, dishes)
    return len(violations) == 0


def violation_count(violations: list[dict]) -> int:
    return len(violations)


def violation_magnitude(violations: list[dict]) -> float:
    """Finite total violation size (structural violations count as large)."""
    total = 0.0
    for v in violations:
        amount = v.get("amount", 0.0)
        total += 1e9 if amount == float("inf") else float(amount)
    return total


__all__ = [
    "DAYS",
    "MEALS_PER_DAY",
    "SLOTS",
    "MEAL_LABELS",
    "EPS",
    "OBJECTIVE_NAMES",
    "TAG_PREFERENCE",
    "SCALAR_WEIGHTS",
    "EnvelopeNotApprovedError",
    "Plan",
    "ConstraintSlot",
    "dish_lookup",
    "sum_nutrients",
    "daily_totals",
    "exclusion_for",
    "allowed_dishes",
    "constraint_layout",
    "constraint_names",
    "constraint_vector",
    "scalar_score",
    "objective_vector",
    "evaluate",
    "is_feasible",
    "violation_count",
    "violation_magnitude",
]
