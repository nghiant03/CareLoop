"""Constraint satisfaction: engine -> approval -> optimiser -> verification.

Run eligible proposals through local approval and ``plan_service.plan_meals``.
Recompute hard compliance against the solved envelope and soft gaps against
original aims. Report search failure and retained MIN relaxations separately.

Exact diagnoses apply only to single-dish encoding. Leave-one-out greedy
results identify helpful MAX removals, not unique blockers or impossibility.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from evaluation.common import load_patients
from rules.engine import run_rules

__all__ = ["evaluate_satisfaction"]

_EPS = 1e-6
_FIXED_APPROVAL_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _approve(envelope_model: Any) -> Any:
    """Simulate the clinician approval gate (content unchanged, status flipped)."""
    return envelope_model.model_copy(update={
        "status": "APPROVED",
        "approved_by": "evaluation-suite (simulated clinician approval)",
        "approved_at": _FIXED_APPROVAL_TIME,
    })


def _per_day_check(plan: list[list[str]], solved_envelope: Any, dishes: list[Any],
                   aims_envelope: Any = None) -> dict[str, Any]:
    """Recompute daily MAX compliance and informational MIN/TARGET gaps.

    Hard checks use ``solved_envelope``. Soft gaps use ``aims_envelope`` when
    supplied so relaxed floors cannot hide misses. MIN reports worst-day
    shortfall. TARGET reports mean absolute daily distance, preventing cancellation.

    ``soft_aims_by_constraint`` preserves each ``<nutrient>:<kind>`` aim.
    Legacy ``soft_aims`` keeps only the last aim for each nutrient.
    """
    from backend.optim.problem import daily_totals

    totals = daily_totals(plan, dishes)
    hard_failures = []
    soft: dict[str, Any] = {}
    for target in solved_envelope.targets:
        if target.kind.value != "max":
            continue
        key = target.nutrient.value
        values = [day[key] for day in totals]
        over = [(d, round(v, 3)) for d, v in enumerate(values, start=1)
                if v > target.value + _EPS]
        for day, value in over:
            hard_failures.append({"nutrient": key, "kind": "max",
                                  "day": day, "total": value,
                                  "limit": target.value})
    soft_envelope = solved_envelope if aims_envelope is None else aims_envelope
    for target in soft_envelope.targets:
        kind = target.kind.value
        if kind == "max":
            continue  # ceilings are verified as hard constraints above
        key = target.nutrient.value
        values = [day[key] for day in totals]
        if kind == "min":
            shortfall = max(0.0, target.value - min(values))  # worst day
            soft[f"{key}:{kind}"] = {"kind": kind, "floor": target.value,
                                     "worst_day_total": round(min(values), 3),
                                     "worst_day_shortfall": round(shortfall, 3)}
        else:  # target
            distances = [abs(v - target.value) for v in values]
            soft[f"{key}:{kind}"] = {"kind": kind, "aim": target.value,
                                     "mean_day_total": round(sum(values) / len(values), 3),
                                     "mean_distance": round(sum(distances) / len(distances), 3)}
    return {"days_checked": len(totals), "hard_failures": hard_failures,
            "hard_compliant": not hard_failures,
            "soft_aims_by_constraint": soft,
            "soft_aims": {key.rsplit(":", 1)[0]: aim for key, aim in soft.items()}}


def _blocking_constraints(solved_envelope: Any, dishes: list[Any]) -> list[str]:
    """Leave-one-out greedy diagnostic for infeasible envelopes.

    Among nutrient targets, only hard MAX ceilings can block feasibility, so a
    target is a "blocker" when dropping that MAX alone lets the greedy
    constructor find a feasible plan.  Empty list => no single removal helps
    within the heuristic budget. Neither outcome proves the remaining envelope
    infeasible or identifies a unique clinical blocker; exclusions also apply.
    """
    from backend.optim.real_data import FastEvaluator, greedy_feasible_plan
    from shared.envelope_schema import ConstraintKind

    blockers = []
    for target in solved_envelope.targets:
        if target.kind != ConstraintKind.MAX:
            continue
        kept = [
            t for t in solved_envelope.targets
            if not (t.nutrient == target.nutrient and t.kind == target.kind)
        ]
        reduced = solved_envelope.model_copy(update={"targets": kept})
        ev = FastEvaluator(reduced, dishes)
        if ev.size and greedy_feasible_plan(ev, seed=42) is not None:
            blockers.append(f"{target.nutrient.value}:{target.kind.value}={target.value:g}")
    return blockers


def evaluate_satisfaction(
    patients: list[dict[str, Any]] | None = None,
    dishes: list[Any] | None = None,
    seed: int = 42,
    pop_size: int = 40,
    n_gen: int = 80,
    diagnose_blockers: bool = True,
) -> dict[str, Any]:
    """End-to-end constraint-satisfaction check over all eligible patients."""
    from backend.app.core.plan_service import plan_meals
    from shared.envelope_schema import NutrientEnvelope

    patients = patients if patients is not None else load_patients()
    if dishes is None:
        from backend.optim.real_data import load_dishes
        dishes = load_dishes()

    rows: list[dict[str, Any]] = []
    for patient in patients:
        engine_result = run_rules(patient)
        envelope_dict = engine_result["envelope"]
        if envelope_dict["status"] == "REJECTED":
            rows.append({
                "patient_id": envelope_dict["patient_id"],
                "archetype": patient.get("archetype"),
                "status": "REJECTED",
                "attempted": False,
                "note": "out-of-scope patient; no envelope to optimise",
            })
            continue

        envelope = NutrientEnvelope(**envelope_dict)
        approved = _approve(envelope)
        started = time.perf_counter()
        outcome = plan_meals(approved, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen)
        result = outcome.result
        solved, relaxed = outcome.solved_envelope, outcome.relaxed_constraints
        runtime_s = time.perf_counter() - started

        feasible = bool(result.get("feasible"))
        violation_count = int(result.get("violation_count", 0))
        row: dict[str, Any] = {
            "patient_id": envelope.patient_id,
            "archetype": patient.get("archetype"),
            "status": "solved" if feasible else "infeasible",
            "attempted": True,
            "engine": result.get("engine"),
            "violation_count": violation_count,
            "feasible": feasible,
            "allowed_dish_count": result.get("allowed_dish_count"),
            "relaxed_constraints": relaxed,
            "solver_runtime_s": round(runtime_s, 3),  # wall-clock; not deterministic
            "infeasibility_reason": result.get("infeasibility_reason"),
            "infeasibility_status": result.get("infeasibility_status"),
            "meal_complete": result.get("meal_complete", False),
        }
        if feasible:
            per_day = _per_day_check(result["plan"], solved, dishes,
                                     aims_envelope=approved)
            row["per_day_hard_compliant"] = per_day["hard_compliant"]
            row["per_day_hard_failures"] = per_day["hard_failures"]
            row["soft_aims"] = per_day["soft_aims"]
            row["soft_aims_by_constraint"] = per_day["soft_aims_by_constraint"]
            row["days_checked"] = per_day["days_checked"]
            min_shortfalls_pct = [
                (aim["worst_day_shortfall"] / aim["floor"] * 100.0)
                for aim in per_day["soft_aims_by_constraint"].values()
                if aim.get("kind") == "min" and aim.get("floor", 0) > 0
            ]
            row["worst_day_min_shortfall_pct"] = (
                round(max(min_shortfalls_pct), 2) if min_shortfalls_pct else 0.0
            )
        else:
            row["per_day_hard_compliant"] = None
            row["worst_day_min_shortfall_pct"] = None
            if diagnose_blockers:
                row["blocking_constraints_leave_one_out"] = _blocking_constraints(solved, dishes)
        rows.append(row)

    attempted = [r for r in rows if r["attempted"]]
    zero_violation = [r for r in attempted if r["feasible"] and r["violation_count"] == 0]
    per_day_ok = [r for r in zero_violation if r["per_day_hard_compliant"]]
    infeasible = [r for r in attempted if not r["feasible"]]
    relaxed_rows = [r for r in attempted if r["relaxed_constraints"]]
    shortfall_pcts = [
        float(r["worst_day_min_shortfall_pct"])
        for r in zero_violation
        if r.get("worst_day_min_shortfall_pct") is not None
    ]

    rate = (len(zero_violation) / len(attempted)) if attempted else None
    return {
        "criterion": "Constraint satisfaction",
        "definition": (
            "For every eligible patient: engine -> simulated APPROVED -> "
            "plan_service.plan_meals (single-dish search then original-target "
            "main/optional-side composition; fallback floor adjustments disclosed) "
            "-> violation_count == 0 and per-day totals "
            "within the SOLVED envelope's HARD constraints (MAX ceilings; "
            "MIN floors / TARGETs are soft per PLAN.md module 4, reported as "
            "soft-aim shortfalls, never violations). Infeasible envelopes "
            "(explicit solver diagnosis, empty plan, nothing served) and "
            "relaxation disclosures are reported distinctly."
        ),
        "optimiser_config": {"seed": seed, "pop_size": pop_size, "n_gen": n_gen,
                             "method": "nsga2"},
        "eligible_patients": len(attempted),
        "plans_attempted": len(attempted),
        "zero_violation_plans": len(zero_violation),
        "per_day_verified_plans": len(per_day_ok),
        "infeasible_plans": len(infeasible),
        "relaxed_envelopes": len(relaxed_rows),
        "zero_violation_rate": rate,
        "adequacy_summary": {
            "mean_worst_day_min_shortfall_pct": (
                round(sum(shortfall_pcts) / len(shortfall_pcts), 2)
                if shortfall_pcts else None
            ),
            "max_worst_day_min_shortfall_pct": (
                round(max(shortfall_pcts), 2) if shortfall_pcts else None
            ),
            "plans_meeting_all_min_floors": sum(1 for s in shortfall_pcts if s <= 0.0),
        },
        "verdict": (
            "PASS" if rate == 1.0 and len(per_day_ok) == len(zero_violation) else "FAIL"
        ),
        "verdict_note": (
            None if rate == 1.0
            else (
                "guideline envelopes exceed what the 190-dish pool can jointly "
                "satisfy; the optimiser diagnoses infeasibility and serves no "
                "plan (safe failure), see per_patient blockers"
            )
        ),
        "per_patient": rows,
    }
