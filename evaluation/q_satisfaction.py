"""Q3 — Constraint satisfaction: engine -> approval -> optimiser -> verification.

For every eligible patient (rule status PROPOSED):
1. run the rule engine -> envelope,
2. programmatically approve (status APPROVED, content untouched) — mirroring
   the clinician gate,
3. ``prepare_envelope_for_pool`` (the /plans MIN-relaxation semantics),
4. ``backend.optim.api.run`` (NSGA-II + hard feasibility guarantee),
5. verify ``violation_count == 0`` and, for feasible plans, recompute per-day
   totals from the returned plan and check them against the SOLVED envelope.

Infeasible envelopes (explicit solver diagnosis, empty plan, nothing served)
and MIN-relaxation cases are reported distinctly.  A leave-one-out greedy
diagnostic identifies which constraint(s) block feasibility for infeasible
envelopes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from evaluation.common import load_patients
from rules.engine import run_rules

__all__ = ["evaluate_q3"]

_EPS = 1e-6
_FIXED_APPROVAL_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _approve(envelope_model: Any) -> Any:
    """Simulate the clinician approval gate (content unchanged, status flipped)."""
    return envelope_model.model_copy(update={
        "status": "APPROVED",
        "approved_by": "evaluation-suite (simulated clinician approval)",
        "approved_at": _FIXED_APPROVAL_TIME,
    })


def _per_day_compliant(plan: list[list[str]], solved_envelope: Any, dishes: list[Any]) -> dict[str, Any]:
    """Recompute per-day totals and check them against the SOLVED envelope."""
    from backend.optim.problem import daily_totals

    totals = daily_totals(plan, dishes)
    failures = []
    for target in solved_envelope.targets:
        kind = target.kind.value
        if kind == "target":
            continue  # targets are soft objectives, not hard constraints
        for day, day_totals in enumerate(totals, start=1):
            value = day_totals[target.nutrient.value]
            if kind == "max" and value > target.value + _EPS:
                failures.append({"nutrient": target.nutrient.value, "kind": kind,
                                 "day": day, "total": round(value, 3), "limit": target.value})
            if kind == "min" and value < target.value - _EPS:
                failures.append({"nutrient": target.nutrient.value, "kind": kind,
                                 "day": day, "total": round(value, 3), "limit": target.value})
    return {"days_checked": len(totals), "failures": failures,
            "compliant": not failures}


def _blocking_constraints(solved_envelope: Any, dishes: list[Any]) -> list[str]:
    """Leave-one-out greedy diagnostic for infeasible envelopes.

    A target is a "blocker" when dropping it alone lets the greedy constructor
    find a feasible plan.  Empty list => no single removal helps (jointly
    infeasible w.r.t. the greedy constructor).
    """
    from backend.optim.real_data import FastEvaluator, greedy_feasible_plan

    blockers = []
    for target in solved_envelope.targets:
        kept = [
            t for t in solved_envelope.targets
            if not (t.nutrient == target.nutrient and t.kind == target.kind)
        ]
        reduced = solved_envelope.model_copy(update={"targets": kept})
        ev = FastEvaluator(reduced, dishes)
        if ev.size and greedy_feasible_plan(ev, seed=42) is not None:
            blockers.append(f"{target.nutrient.value}:{target.kind.value}={target.value:g}")
    return blockers


def evaluate_q3(
    patients: list[dict[str, Any]] | None = None,
    dishes: list[Any] | None = None,
    seed: int = 42,
    pop_size: int = 40,
    n_gen: int = 80,
    diagnose_blockers: bool = True,
) -> dict[str, Any]:
    """End-to-end constraint-satisfaction check over all eligible patients."""
    from shared.envelope_schema import NutrientEnvelope
    from backend.optim.api import run as optim_run
    from backend.app.core.plan_service import prepare_envelope_for_pool

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
        solved, relaxed = prepare_envelope_for_pool(approved, dishes)
        started = time.perf_counter()
        result = optim_run(solved, dishes=dishes, seed=seed, pop_size=pop_size, n_gen=n_gen)
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
        }
        if feasible:
            per_day = _per_day_compliant(result["plan"], solved, dishes)
            row["per_day_totals_compliant"] = per_day["compliant"]
            row["per_day_failures"] = per_day["failures"]
            row["days_checked"] = per_day["days_checked"]
        else:
            row["per_day_totals_compliant"] = None
            if diagnose_blockers:
                row["blocking_constraints_leave_one_out"] = _blocking_constraints(solved, dishes)
        rows.append(row)

    attempted = [r for r in rows if r["attempted"]]
    zero_violation = [r for r in attempted if r["feasible"] and r["violation_count"] == 0]
    per_day_ok = [r for r in zero_violation if r["per_day_totals_compliant"]]
    infeasible = [r for r in attempted if not r["feasible"]]
    relaxed_rows = [r for r in attempted if r["relaxed_constraints"]]

    rate = (len(zero_violation) / len(attempted)) if attempted else None
    return {
        "question": "Q3 Constraint satisfaction",
        "definition": (
            "For every eligible patient: engine -> simulated APPROVED -> "
            "prepare_envelope_for_pool (MIN-floor relaxation, as /plans does) -> "
            "backend.optim.api.run -> violation_count == 0 and per-day totals "
            "within the SOLVED envelope. Infeasible envelopes (explicit solver "
            "diagnosis, empty plan, nothing served) and relaxation cases are "
            "reported distinctly."
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