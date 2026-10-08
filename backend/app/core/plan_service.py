"""Planning service: envelope preparation + optimiser result mapping.

Two reconciliations live here (documented for the frontend contract):

1. **MIN-floor relaxation (objective calibration + disclosure).** Under the
   PLAN.md module-4 encoding, MIN floors and TARGETs are *soft* objective
   terms — they steer the nutrient-deviation objective and never cause
   infeasibility, so relaxation is no longer required for feasibility.
   ``prepare_envelope_for_pool`` still lowers MIN floors the allowed pool
   provably cannot reach (e.g. the guideline fibre floors ``GEN-FIBER-25``
   min 25 g/d / ``DASH-2025-FIBER-30`` min 30 g/d vs a pool that tops out at
   8 g fibre per dish, 24 g per 3-dish day) and reports every adjustment in
   ``relaxed_constraints``.  The hard-constraint guarantee
   (``violation_count == 0``) holds against the envelope actually solved, and
   the relaxation is fully disclosed instead of silently dropping the
   guideline intent.

2. **Frontend plan shape.** The optimiser returns ``plan`` as 21 flat slots
   (day-major, list of dish-id lists) plus objectives/violations. This module
   maps that to the UI contract: ``days[]`` with ``slots[]`` (dish entries with
   names + nutrients) and ``totals[]`` (per-nutrient daily totals vs targets).

   The response also carries a top-level ``adequacy[]`` array scored against
   the ORIGINAL clinician-approved envelope (one entry per MIN/TARGET
   constraint, MAX ceilings excluded): ``aim`` (approved value),
   ``mean_daily`` / ``worst_day`` / ``worst_daily`` across the plan,
   ``shortfall`` / ``shortfall_pct`` (positive = the approved aim was not met
   on the worst day), ``met_days`` / ``total_days``, and ``relaxed_aim`` (the
   solved floor when MIN relaxation moved it, else ``null``). Because MIN
   floors are soft objective terms, ``feasible == true`` with
   ``violation_count == 0`` does not guarantee the approved aims were met —
   ``adequacy`` makes every shortfall against the approved envelope visible.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.envelope_schema import (
    ConstraintKind,
    NutrientEnvelope,
)

from backend.app.explain.views import patient_explanation
from backend.optim.problem import MEAL_LABELS, MEALS_PER_DAY, NUTRIENT_KEYS, allowed_dishes

__all__ = ["prepare_envelope_for_pool", "map_plan_result"]

_EPS = 1e-9


def prepare_envelope_for_pool(
    envelope: NutrientEnvelope, dishes: list[Any]
) -> tuple[NutrientEnvelope, list[dict[str, Any]]]:
    """Lower MIN floors the allowed dish pool provably cannot reach.

    Returns ``(envelope_to_solve, relaxed_constraints)``. The input envelope is
    never mutated; when nothing needs relaxing the original object comes back
    with an empty ``relaxed_constraints`` list.
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
                            f"guideline floor {target.value:g} {target.unit}/day is "
                            f"unreachable: the three highest-{target.nutrient.value} "
                            f"dishes in the allowed pool reach at most {achievable:g} "
                            f"{target.unit}/day; floor lowered so a feasible plan "
                            f"can be produced (was disclosed in the plan response)"
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
    relaxed_constraints: Optional[list[dict[str, Any]]] = None,
    solved_envelope: Optional[NutrientEnvelope] = None,
) -> dict[str, Any]:
    """Map the optimiser result to the frontend plan contract.

    ``envelope`` is the clinician-approved envelope (drives the patient
    explanation); ``solved_envelope`` is the possibly MIN-relaxed copy the
    optimiser actually solved (drives totals-vs-target compliance so the
    reported ``compliant`` flags match ``violation_count == 0``).

    ``compliant`` reflects HARD constraints only (MAX ceilings — the PLAN.md
    module-4 encoding): a nutrient whose day total exceeds a hard MAX is
    ``False``; a nutrient with no hard MAX is ``None`` even when a soft MIN
    floor is unmet (the shortfall stays visible in ``targets``).

    The top-level ``adequacy[]`` array is scored against the ORIGINAL approved
    ``envelope`` (not the relaxed copy): one entry per MIN/TARGET constraint in
    envelope order, reporting mean/worst daily delivery, shortfall vs the
    approved aim, and the relaxed floor when it differs from the aim. Empty
    when the plan is infeasible.
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
        totals = []
        nutrients_with_targets = set(targets_by_nutrient)
        for key in NUTRIENT_KEYS:
            if key not in nutrients_with_targets and totals_raw.get(key, 0.0) == 0.0:
                continue
            value = round(totals_raw.get(key, 0.0), 3)
            constraints = targets_by_nutrient.get(key, [])
            compliant: Optional[bool] = None
            for constraint in constraints:
                if constraint["kind"] == "max":
                    ok = value <= constraint["value"] + _EPS
                elif constraint["kind"] == "min":
                    # MIN floors are soft objective terms under the PLAN.md
                    # module-4 encoding — a shortfall is not a hard violation
                    # (it stays visible in `targets` for the UI).
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
            f"Note: your {rc['nutrient'].rsplit('_', 1)[0]} goal was lowered from "
            f"{rc['requested']:g} to {rc['relaxed_to']:g} {rc['unit']} a day "
            "because the current food database cannot reach the guideline "
            "floor; a clinician can review this."
            for rc in relaxed_constraints
        ]
        explanation["relaxation_notes"] = notes

    feasible = bool(result.get("feasible"))

    # Adequacy vs the ORIGINAL clinician-approved envelope: one entry per
    # MIN/TARGET constraint in envelope order (MAX ceilings are excluded —
    # ceiling compliance is reported via totals.compliant). Because MIN floors
    # are soft objective terms, a plan can be feasible with zero hard
    # violations while still missing the approved aims; this makes that gap
    # visible instead of scoring only against the relaxed copy.
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
            aim = round(constraint.value, 3)
            series = [day_totals.get(key, 0.0) for day_totals in daily_raw_totals]
            worst_index = min(range(len(series)), key=lambda i: series[i])
            worst_daily = round(series[worst_index], 3)
            shortfall = round(aim - worst_daily, 3)
            shortfall_pct = round(shortfall / aim * 100.0, 3) if aim > _EPS else 0.0
            relaxed_aim: Optional[float] = None
            solved_aim = solved_aim_by_key.get((key, kind))
            if solved_aim is not None and abs(solved_aim - aim) > _EPS:
                relaxed_aim = round(solved_aim, 3)
            adequacy.append(
                {
                    "nutrient": key,
                    "kind": kind,
                    "unit": constraint.unit,
                    "aim": aim,
                    "mean_daily": round(sum(series) / len(series), 3),
                    "worst_day": worst_index + 1,
                    "worst_daily": worst_daily,
                    "shortfall": shortfall,
                    "shortfall_pct": shortfall_pct,
                    "met_days": sum(1 for value in series if value >= aim - _EPS),
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
                if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                    cleaned[key] = None
            safe.append(cleaned)
        return safe

    out = {
        "envelope_id": result.get("envelope_id") or envelope.envelope_id,
        "patient_id": result.get("patient_id") or envelope.patient_id,
        "feasible": feasible,
        "engine": result.get("engine"),
        "violation_count": result.get("violation_count", 0),
        "runtime_ms": result.get("runtime_ms"),
        "objectives": result.get("objectives"),
        "allowed_dish_count": result.get("allowed_dish_count"),
        "infeasibility_reason": result.get("infeasibility_reason"),
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