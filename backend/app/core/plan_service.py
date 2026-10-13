"""Shared planning policy and frontend response mapping.

Single-dish search may calibrate unreachable soft MIN floors; main/side
composition and adequacy reporting retain the original input aims. Floor
changes are disclosed separately from hard feasibility. See
``docs/ARCHITECTURE.md`` for the planning workflow and clinical contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isinf, isnan
from typing import Any

from backend.app.explain.views import patient_explanation
from backend.optim.api import run as optimise
from backend.optim.composition import improve_meals
from backend.optim.problem import (
    MEAL_LABELS,
    MEALS_PER_DAY,
    NUTRIENT_KEYS,
    allowed_dishes,
)
from backend.optim.toy_data import Dish
from shared.envelope_schema import (
    ConstraintKind,
    NutrientEnvelope,
)

__all__ = ["PlanningOutcome", "map_plan_result", "plan_meals", "prepare_envelope_for_pool"]

_EPS = 1e-9


@dataclass
class PlanningOutcome:
    result: dict[str, Any]
    solved_envelope: NutrientEnvelope
    relaxed_constraints: list[dict[str, Any]]


def plan_meals(envelope: NutrientEnvelope, dishes: list[Dish], *, seed: int = 42,
               pop_size: int = 40, n_gen: int = 80) -> PlanningOutcome:
    """Solve and compose meals without persisting clinical state.

    Live callers must first enforce the approval gate: an APPROVED,
    scope-eligible envelope with nonempty targets. The optimiser checks status
    but this helper does not enforce scope or target readiness. Simulation and
    evaluation callers supply locally approved copies, not live approvals.

    API planning, simulations, and evaluation share this policy. Composition
    scores the original aims; only the single-dish fallback uses relaxed floors.
    """
    solved, relaxed = prepare_envelope_for_pool(envelope, dishes)
    result = optimise(solved, dishes=dishes, seed=seed, pop_size=pop_size, n_gen=n_gen)
    result = improve_meals(result, envelope, dishes, seed=seed)
    if result.get("meal_complete"):
        solved, relaxed = envelope, []
    return PlanningOutcome(result, solved, relaxed)


def prepare_envelope_for_pool(
    envelope: NutrientEnvelope, dishes: list[Any]
) -> tuple[NutrientEnvelope, list[dict[str, Any]]]:
    """Calibrate soft MIN floors to the single-dish-per-meal search bound.

    Returns ``(envelope_to_solve, relaxed_constraints)``. The input envelope is
    never mutated; when nothing needs relaxing the original object comes back
    with an empty ``relaxed_constraints`` list.

    Bounds use three servings of each nutrient's highest-valued allowed dish,
    without proving joint attainability or MAX compliance. Even a relaxed copy
    shares unchanged target objects with the input; callers must not mutate them.
    """
    pool = allowed_dishes(envelope, dishes)
    reachable_max: dict[str, float] = {}
    for dish in pool:
        for key in NUTRIENT_KEYS:
            value = dish.nutrient(key)
            if value > reachable_max.get(key, 0.0):
                reachable_max[key] = value

    relaxed: list[dict[str, Any]] = []
    targets = []
    for target in envelope.targets:
        if target.kind == ConstraintKind.MIN:
            achievable = round(3.0 * reachable_max.get(target.nutrient.value, 0.0), 3)
            if achievable < target.value - _EPS:
                relaxed.append(
                    {
                        "nutrient": target.nutrient.value,
                        "kind": "min",
                        "requested": target.value,
                        "relaxed_to": achievable,
                        "unit": target.unit,
                        "reason": (
                            f"approved floor {target.value:g} {target.unit}/day is "
                            f"unreachable with one dish per meal: three servings of "
                            f"the highest-{target.nutrient.value} dish reach at most "
                            f"{achievable:g} {target.unit}/day; the soft solver floor "
                            f"was lowered, while adequacy retains the approved aim"
                        ),
                    }
                )
                target = target.model_copy(update={"value": achievable})
        targets.append(target)

    if not relaxed:
        return envelope, []
    solved = envelope.model_copy(deep=True)
    solved.targets = targets
    return solved, relaxed


def map_plan_result(
    result: dict[str, Any],
    envelope: NutrientEnvelope,
    dishes: list[Any],
    relaxed_constraints: list[dict[str, Any]] | None = None,
    solved_envelope: NutrientEnvelope | None = None,
) -> dict[str, Any]:
    """Map the optimiser result to the frontend plan contract.

    ``envelope`` supplies original aims and explanations. ``solved_envelope``
    supplies displayed constraints, including relaxed floors. Leave both unchanged.

    Map day-major meals to ``days[].slots`` and totals. ``compliant`` checks
    MAX only and is None without a ceiling. ``adequacy`` scores original
    MIN/TARGET aims in envelope order. Legacy ``shortfall`` keys include TARGET
    overshoots. Decide before rounding. Infeasible results have no days or adequacy.
    """
    solved = solved_envelope or envelope
    lookup = {d.dish_id: d for d in dishes}
    plan = result.get("plan") or []
    n_days = max(len(plan) // MEALS_PER_DAY, 0)

    targets_by_nutrient: dict[str, list[dict[str, Any]]] = {}
    for target in solved.targets:
        targets_by_nutrient.setdefault(target.nutrient.value, []).append(
            {
                "kind": target.kind.value,
                "value": target.value,
                "unit": target.unit,
            }
        )

    days = []
    day1_totals: dict[str, float] = {}
    daily_raw_totals: list[dict[str, float]] = []
    for day in range(n_days):
        day_slots = plan[day * MEALS_PER_DAY : (day + 1) * MEALS_PER_DAY]
        slots = []
        totals_raw = {key: 0.0 for key in NUTRIENT_KEYS}
        for meal_index, dish_ids in enumerate(day_slots):
            for dish_id in dish_ids or []:
                dish = lookup.get(dish_id)
                if dish is None:
                    continue
                totals_raw = {
                    key: value + dish.nutrient(key) for key, value in totals_raw.items()
                }
                slots.append(
                    {
                        "meal": MEAL_LABELS[meal_index] if meal_index < len(MEAL_LABELS) else str(meal_index),
                        "dish_id": dish.dish_id,
                        "name": dish.name,
                        "category": dish.category,
                        "nutrients": {
                            key: dish.nutrient(key) for key in NUTRIENT_KEYS
                        },
                    }
                )
        totals: list[dict[str, Any]] = []
        nutrients_with_targets = set(targets_by_nutrient)
        for key in NUTRIENT_KEYS:
            if key not in nutrients_with_targets and totals_raw.get(key, 0.0) == 0.0:
                continue
            raw_value = totals_raw.get(key, 0.0)
            value = round(raw_value, 3)
            constraints = targets_by_nutrient.get(key, [])
            compliant: bool | None = None
            for constraint in constraints:
                if constraint["kind"] == "max":
                    ok = raw_value <= constraint["value"] + _EPS
                elif constraint["kind"] == "min":
                    # Soft floors do not change hard-compliance flags.
                    continue
                else:
                    continue
                compliant = ok if compliant is None else (compliant and ok)
            totals.append(
                {
                    "nutrient": key,
                    "unit": constraint_unit(constraints),
                    "value": value,
                    "targets": constraints,
                    "compliant": compliant,
                }
            )
        if day == 0:
            day1_totals = {t["nutrient"]: t["value"] for t in totals}
        daily_raw_totals.append(dict(totals_raw))
        days.append({"day": day + 1, "slots": slots, "totals": totals})

    envelope_dump = envelope.model_dump(by_alias=True)
    explanation = patient_explanation(
        envelope_dump, plan={"totals": day1_totals} if day1_totals else None
    )
    if relaxed_constraints:
        notes = [
            f"Note: the solver's {rc['nutrient'].rsplit('_', 1)[0]} floor was lowered from "
            f"{rc['requested']:g} to {rc['relaxed_to']:g} {rc['unit']} a day "
            "for the one-dish-per-meal search. Your approved goal remains "
            "unchanged in the adequacy assessment."
            for rc in relaxed_constraints
        ]
        explanation["relaxation_notes"] = notes

    feasible = bool(result.get("feasible"))

    # Score original aims, not solver-calibrated floors, so relaxation cannot hide gaps.
    adequacy: list[dict[str, Any]] = []
    if feasible and n_days:
        solved_aim_by_key: dict[tuple[str, str], float] = {}
        for target in solved.targets:
            solved_aim_by_key.setdefault((target.nutrient.value, target.kind.value), target.value)
        for constraint in envelope.targets:
            kind = constraint.kind.value
            if kind == "max":
                continue
            key = constraint.nutrient.value
            aim = constraint.value
            series = [day_totals.get(key, 0.0) for day_totals in daily_raw_totals]
            deviations = [abs(aim - value) if kind == "target" else max(0., aim - value) for value in series]
            worst_index = max(range(len(series)), key=lambda i: deviations[i])
            worst_daily = round(series[worst_index], 3)
            deviation = round(deviations[worst_index], 3)
            deviation_pct = round(deviations[worst_index] / aim * 100.0, 3) if aim > _EPS else 0.0
            relaxed_aim: float | None = None
            solved_aim = solved_aim_by_key.get((key, kind))
            if solved_aim is not None and abs(solved_aim - aim) > _EPS:
                relaxed_aim = round(solved_aim, 3)
            adequacy.append(
                {
                    "nutrient": key,
                    "kind": kind,
                    "unit": constraint.unit,
                    "aim": round(aim, 3),
                    "mean_daily": round(sum(series) / len(series), 3),
                    "worst_day": worst_index + 1,
                    "worst_daily": worst_daily,
                    # Retain wire keys used by saved plans; TARGET deviations include overshoots.
                    "shortfall": deviation,
                    "shortfall_pct": deviation_pct,
                    "met_days": sum(1 for deviation in deviations if deviation <= _EPS),
                    "total_days": len(series),
                    "relaxed_aim": relaxed_aim,
                }
            )

    def _json_safe_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """JSON has no Infinity — blank out non-finite magnitudes."""
        safe = []
        for violation in violations or []:
            cleaned = dict(violation)
            for key in ("amount", "actual", "limit"):
                value = cleaned.get(key)
                if isinstance(value, float) and (isnan(value) or isinf(value)):
                    cleaned[key] = None
            safe.append(cleaned)
        return safe

    out = {
        "data_quality": {
            "unverified_dishes": sum(not getattr(d, "verified", False) for d in dishes),
            "dish_count": len(dishes),
            "cost_is_estimated": any(getattr(d, "price_is_estimated", False) for d in dishes),
        },
        "envelope_version": envelope.version,
        "meal_complete": result.get("meal_complete", False),
        "meal_encoding": result.get("meal_encoding", "single_dish"),
        "selection": result.get("selection", "scalar"),
        "seed": result.get("seed", 42),
        "role_annotations": result.get("role_annotations"),
        "adequate": bool(feasible and adequacy and all(a["met_days"] == n_days for a in adequacy)),
        "envelope_id": result.get("envelope_id") or envelope.envelope_id,
        "patient_id": result.get("patient_id") or envelope.patient_id,
        "feasible": feasible,
        "engine": result.get("engine"),
        "violation_count": result.get("violation_count", 0),
        "runtime_ms": result.get("runtime_ms"),
        "objectives": result.get("objectives"),
        "allowed_dish_count": result.get("allowed_dish_count"),
        "infeasibility_reason": result.get("infeasibility_reason"),
        "infeasibility_status": result.get("infeasibility_status"),
        "exact_reference": result.get("exact_reference"),
        "hard_feasible": feasible,
        "violations": _json_safe_violations(result.get("violations") or []),
        "relaxed_constraints": relaxed_constraints or [],
        "days": days if feasible else [],
        "adequacy": adequacy,
        "explanation": explanation,
        "status": envelope.status.value if hasattr(envelope.status, "value") else str(envelope.status),
    }
    return out


def constraint_unit(constraints: list[dict[str, Any]]) -> str:
    for constraint in constraints:
        if constraint.get("unit"):
            return constraint["unit"]
    return ""
