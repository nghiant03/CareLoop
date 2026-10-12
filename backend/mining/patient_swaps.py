"""Validate ranked dish swaps against an envelope and saved-plan context.

Generic rankings from ``backend.mining.substitutions`` do not enforce patient
constraints. Suggestions replace every source occurrence in the supplied saved
plan and validate the whole result with ``problem.evaluate``. Main/optional-side
plans must also retain meal roles. Deltas describe saved-plan changes, not intake.

Envelopes: suggestion helpers may evaluate any lifecycle status; the API labels
unapproved suggestions ``informational_only``. Applying a swap requires a ready
approved envelope. For local evaluation, unapproved inputs receive an APPROVED
deep copy; already-approved inputs are reused. These helpers do not persist
envelopes or approvals. The apply endpoint separately saves a derived plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.mining.substitutions import suggest_substitutions
from backend.optim.composition import complete_meals
from backend.optim.problem import (
    MEALS_PER_DAY,
    NUTRIENT_KEYS,
    Plan,
    evaluate,
    exclusion_for,
)
from shared.envelope_schema import ConstraintKind, EnvelopeStatus, NutrientEnvelope

__all__ = [
    "DishNotInPlanError",
    "SwapOutcome",
    "affected_days_for",
    "apply_patient_swap",
    "patient_substitutions",
    "plan_from_document",
]

_MEAL_ORDER = ("breakfast", "lunch", "dinner")


class DishNotInPlanError(Exception):
    """The dish to swap does not occur anywhere in the patient's plan."""


# ---------------------------------------------------------------------------
# Plan reconstruction (stored UI contract -> solver Plan)
# ---------------------------------------------------------------------------


def plan_from_document(document: dict[str, Any]) -> Plan:
    """Reconstruct the day-major solver ``Plan`` from a stored plan document.

    Sort ``days[]`` by day number and group their slots as breakfast, lunch,
    dinner. Missing meals remain empty; unknown meal labels go into dinner.
    Skip slots without a dish ID, but do not validate catalogue membership.
    The response mapper already omits unknown dishes from generated documents.
    Leave the document unchanged.
    """
    days = document.get("days") or []
    plan: Plan = []
    for day in sorted(
        (d for d in days if isinstance(d, dict)),
        key=lambda d: d.get("day", 0),
    ):
        buckets: list[list[str]] = [[] for _ in _MEAL_ORDER]
        for slot in day.get("slots") or []:
            dish_id = slot.get("dish_id")
            if not dish_id:
                continue
            meal = str(slot.get("meal", "")).lower()
            index = (
                _MEAL_ORDER.index(meal)
                if meal in _MEAL_ORDER
                else len(_MEAL_ORDER) - 1
            )
            buckets[index].append(str(dish_id))
        plan.extend(buckets)
    return plan


def affected_days_for(plan: Plan, dish_id: str) -> list[int]:
    """0-based indices of the plan days in which ``dish_id`` occurs."""
    affected: list[int] = []
    for day in range(len(plan) // MEALS_PER_DAY):
        lo, hi = day * MEALS_PER_DAY, (day + 1) * MEALS_PER_DAY
        if any(dish_id in meal for meal in plan[lo:hi]):
            affected.append(day)
    return affected


def _replace_in_plan(plan: Plan, dish_id: str, replacement: str) -> Plan:
    """Every occurrence of ``dish_id`` becomes ``replacement`` (new plan)."""
    return [
        [replacement if d == dish_id else d for d in meal] for meal in plan
    ]


def _replace_in_day(plan: Plan, day: int, dish_id: str, replacement: str) -> Plan:
    """Replace every occurrence of ``dish_id`` within one day only."""
    lo, hi = day * MEALS_PER_DAY, (day + 1) * MEALS_PER_DAY
    modified = [list(meal) for meal in plan]
    for meal in modified[lo:hi]:
        for index, dish in enumerate(meal):
            if dish == dish_id:
                meal[index] = replacement
    return modified


def _day_totals(plan: Plan, day: int, lookup: dict[str, Any]) -> dict[str, float]:
    lo, hi = day * MEALS_PER_DAY, (day + 1) * MEALS_PER_DAY
    totals = {key: 0.0 for key in NUTRIENT_KEYS}
    for meal in plan[lo:hi]:
        for dish_id in meal:
            dish = lookup.get(dish_id)
            if dish is None:
                continue
            for key in NUTRIENT_KEYS:
                totals[key] += dish.nutrient(key)
    return totals


def _approval_safe_copy(envelope: NutrientEnvelope) -> NutrientEnvelope:
    """Return an APPROVED evaluation input without changing the supplied status.

    Already-approved inputs are returned by identity; callers must not mutate
    them. Other inputs receive a deep copy with local approval solely to satisfy
    ``problem.evaluate``. That copy must not be stored or journalled. This does
    not authorize applying a swap; the endpoint enforces readiness separately.
    """
    if getattr(envelope, "status", None) == EnvelopeStatus.APPROVED:
        return envelope
    local = envelope.model_copy(deep=True)
    local.status = EnvelopeStatus.APPROVED
    return local


def _worst_aim_deviation_pct(
    day_totals: dict[int, dict[str, float]], envelope: NutrientEnvelope
) -> float:
    """Worst MIN shortfall or absolute TARGET deviation as a percentage.

    Pool only the supplied affected days. Exclude MAX ceilings because they are
    hard constraints, not aims. Return 0.0 when no positive aim contributes.
    """
    worst = 0.0
    for totals in day_totals.values():
        for constraint in envelope.targets:
            if constraint.kind not in (ConstraintKind.MIN, ConstraintKind.TARGET):
                continue
            aim = float(constraint.value)
            if aim <= 0.0:
                continue
            delta = aim - totals.get(constraint.nutrient.value, 0.0)
            deviation = abs(delta) if constraint.kind == ConstraintKind.TARGET else max(0., delta)
            worst = max(worst, deviation / aim * 100.0)
    return round(worst, 3)


# ---------------------------------------------------------------------------
# Patient-aware suggestions
# ---------------------------------------------------------------------------


def patient_substitutions(
    dish_id: str,
    k: int,
    envelope: NutrientEnvelope,
    plan_document: dict[str, Any],
    dishes: list[Any],
) -> dict[str, Any]:
    """Rank and validate substitute dishes against the supplied saved plan.

    For positive ``k``, inspect up to ``k * 3`` v2-ranked candidates and return
    at most ``k`` survivors. Replace every source occurrence and reject any
    whole-plan hard violation or main/optional-side role mismatch, including
    violations on unchanged days. Return affected-day nutrient deltas as
    after minus before, and the price difference times replaced occurrences.

    Raise ``KeyError`` for an unknown source or ``DishNotInPlanError`` when it
    is absent from the plan. Local approval copies follow the module contract;
    suggestions do not persist state or authorize applying a swap.
    """
    lookup = {d.dish_id: d for d in dishes}
    source = lookup.get(dish_id)
    if source is None:
        raise KeyError(f"unknown dish_id: {dish_id}")

    plan = plan_from_document(plan_document)
    affected = affected_days_for(plan, dish_id)
    if not affected:
        raise DishNotInPlanError(f"dish {dish_id!r} does not occur in the selected plan")
    occurrences = sum(
        sum(meal.count(dish_id) for meal in plan[day * MEALS_PER_DAY:(day + 1) * MEALS_PER_DAY])
        for day in affected
    )

    candidates = suggest_substitutions(dish_id, k=max(k * 3, k), version=2)
    validation_envelope = _approval_safe_copy(envelope)
    before = {day: _day_totals(plan, day, lookup) for day in affected}

    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["dish_id"]
        candidate_dish = lookup.get(candidate_id)
        if candidate_dish is None:
            continue
        # Generic similarity ranking alone does not enforce the patient's exclusions.
        if exclusion_for(candidate_dish, validation_envelope) is not None:
            continue

        after: dict[int, dict[str, float]] = {}
        full_swap = _replace_in_plan(plan, dish_id, candidate_id)
        _, full_violations = evaluate(full_swap, validation_envelope, dishes)
        if full_violations:
            continue
        if plan_document.get("meal_encoding") == "main_optional_side" and not complete_meals(full_swap, dishes):
            continue
        for day in affected:
            modified = full_swap
            after[day] = _day_totals(modified, day, lookup)

        item = dict(candidate)
        item["day_deltas"] = {
            str(day + 1): {
                key: round(after[day][key] - before[day][key], 3)
                for key in NUTRIENT_KEYS
            }
            for day in affected
        }
        item["cost_delta"] = round(
            (candidate_dish.price_sgd - source.price_sgd) * occurrences, 4
        )
        item["passes_hard_checks"] = True
        # Retain the public field name; TARGET deviations include overshoots.
        item["worst_aim_shortfall_pct"] = _worst_aim_deviation_pct(after, envelope)
        validated.append(item)
        if len(validated) == k:
            break

    return {
        "affected_days": [day + 1 for day in affected],
        "substitutions": validated,
        "candidates_evaluated": len(candidates),
    }


# ---------------------------------------------------------------------------
# Applying a swap
# ---------------------------------------------------------------------------


@dataclass
class SwapOutcome:
    """Result of applying a patient swap to a stored plan."""

    modified_plan: Plan
    objectives: dict[str, float]
    violations: list[dict[str, Any]]
    occurrences_replaced: int
    affected_days: list[int] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return not self.violations


def apply_patient_swap(
    dish_id: str,
    replacement_dish_id: str,
    plan_document: dict[str, Any],
    envelope: NutrientEnvelope,
    dishes: list[Any],
) -> SwapOutcome:
    """Replace every occurrence of ``dish_id`` and re-check the whole plan.

    Raises :class:`KeyError` when either dish is unknown to the dish pool and
    :class:`DishNotInPlanError` when the source dish occurs nowhere in the
    plan. Return hard-constraint and main/optional-side role failures in
    ``violations`` for the caller to reject. Non-APPROVED inputs fail the
    evaluator's gate. Neither the source document nor persistent state is changed.
    """
    lookup = {d.dish_id: d for d in dishes}
    if dish_id not in lookup:
        raise KeyError(f"unknown dish_id: {dish_id}")
    if replacement_dish_id not in lookup:
        raise KeyError(f"unknown dish_id: {replacement_dish_id}")

    plan = plan_from_document(plan_document)
    occurrences = sum(meal.count(dish_id) for meal in plan)
    if occurrences == 0:
        raise DishNotInPlanError(
            f"dish {dish_id!r} does not occur in the patient's plan"
        )

    modified = _replace_in_plan(plan, dish_id, replacement_dish_id)
    objectives, violations = evaluate(modified, envelope, dishes)
    if plan_document.get("meal_encoding") == "main_optional_side" and not complete_meals(modified, dishes):
        violations.append({"type": "meal_role", "detail": "Replacement does not fit the meal's main/side role"})
    return SwapOutcome(
        modified_plan=modified,
        objectives=objectives,
        violations=violations,
        occurrences_replaced=occurrences,
        affected_days=[day + 1 for day in affected_days_for(plan, dish_id)],
    )
