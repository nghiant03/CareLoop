"""Clinician what-if simulations (Milestone 2).

``POST /simulations`` compares a PROPOSED target change against the
patient's current approved envelope + latest saved plan:

* the base side scores the saved plan against the ORIGINAL approved envelope
  (feasibility, hard violations, the 4 objectives, per-aim worst-day
  shortfall, cost);
* the simulated side re-runs the exact ``POST /plans`` flow
  (``prepare_envelope_for_pool`` -> optimiser ``run`` -> ``map_plan_result``)
  against a SIMULATED envelope — a deep copy of the approved envelope with
  the proposed targets substituted, status forced to APPROVED and
  ``envelope_id`` prefixed ``SIM-``.  The simulated envelope is a pure local
  object: it is NEVER written to the envelope store or the lifecycle journal
  (safety by construction — nothing in this module calls ``put_envelope``),
  and no plan row is created, so simulations are read-only over live state.
* ``deltas`` quantifies the change (cost, deviation, variety, pooled
  worst-day shortfall, count of changed meal slots when a base plan exists).
  An infeasible simulated solve is reported (``feasible: false`` +
  ``infeasibility_reason``/``infeasibility_status``) with the delta fields
  that still make sense; the rest are ``null``.

Note on the simulated explanation: ``map_plan_result`` is called with the
SIMULATED envelope as the "original", so the simulated adequacy panel (and
explanation) describes the SIMULATED targets — that is the point of the
what-if.  The base side keeps scoring against the real approved aims.

Comparisons are persisted via ``persistence.save_simulation`` (base
envelope id + proposed targets + full comparison) and listed with
``GET /simulations?patient_id=`` in chronological order.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.core.approval_gate import (
    EnvelopeNotApprovedError,
    find_latest_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result, prepare_envelope_for_pool
from backend.app.models.envelope import EnvelopeStatus, NutrientConstraint
from backend.mining.patient_swaps import plan_from_document
from backend.optim.problem import evaluate

router = APIRouter(prefix="/simulations", tags=["simulations"])


class SimulationRequest(BaseModel):
    """Body for ``POST /simulations``."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    targets: list[NutrientConstraint]


def _pooled_worst_shortfall_pct(adequacy: Optional[list[dict[str, Any]]]) -> float:
    """Worst per-aim relative shortfall across the panel (0.0 when empty)."""
    values = [
        float(entry.get("shortfall_pct") or 0.0)
        for entry in (adequacy or [])
        if entry.get("shortfall_pct") is not None
    ]
    return round(max(values), 3) if values else 0.0


def _meals_changed(base_plan, simulated_plan) -> Optional[int]:
    """Count of day-major slots whose dish sets differ."""
    if base_plan is None or simulated_plan is None:
        return None
    total = 0
    length = max(len(base_plan), len(simulated_plan))
    for index in range(length):
        base_slot = sorted(base_plan[index]) if index < len(base_plan) else None
        sim_slot = sorted(simulated_plan[index]) if index < len(simulated_plan) else None
        if base_slot != sim_slot:
            total += 1
    return total


def _side_summary(
    envelope_id: str,
    plan_id: Optional[str],
    feasible: Optional[bool],
    violation_count: Optional[int],
    objectives: Optional[dict[str, float]],
    adequacy_summary: Optional[list[dict[str, Any]]],
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = {
        "envelope_id": envelope_id,
        "plan_id": plan_id,
        "feasible": feasible,
        "violation_count": violation_count,
        "objectives": objectives,
        "adequacy_summary": adequacy_summary,
        "cost": objectives.get("cost") if objectives else None,
    }
    if extra:
        out.update(extra)
    return out


@router.post("", summary="What-if: re-plan against proposed nutrient targets")
def create_simulation(req: SimulationRequest) -> dict[str, Any]:
    from backend.app.api.plans import _load_dishes, _load_optimiser
    from backend.app.core import persistence

    envelope = find_latest_envelope_for_patient(req.patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": req.patient_id},
        )
    if not envelope.is_ready_for_optimisation():
        raise EnvelopeNotApprovedError(envelope)

    dishes = _load_dishes()
    if dishes is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "dish_database_unavailable",
                "message": "data/dishes.json could not be loaded.",
            },
        )
    optimiser = _load_optimiser()
    run = getattr(optimiser, "run", None) or getattr(optimiser, "optimise", None) if optimiser else None
    if run is None:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "optimiser_not_implemented",
                "message": "backend.optim is not available yet (Lane B, Week 1).",
                "envelope_id": envelope.envelope_id,
            },
        )

    # ---- base side: the saved plan vs the ORIGINAL approved envelope ----
    plan_summary = persistence.latest_plan_for_patient(req.patient_id)
    base_plan: Optional[list] = None
    if plan_summary is not None:
        plan_document = persistence.get_plan(plan_summary["plan_id"]) or {}
        if plan_document.get("days"):
            base_plan = plan_from_document(plan_document)
    if base_plan:
        base_objectives, base_violations = evaluate(base_plan, envelope, dishes)
        base_mapped = map_plan_result(
            {
                "plan": base_plan,
                "feasible": not base_violations,
                "violation_count": len(base_violations),
            },
            envelope,
            dishes,
        )
        base = _side_summary(
            envelope.envelope_id,
            plan_summary["plan_id"],
            not base_violations,
            len(base_violations),
            base_objectives,
            base_mapped.get("adequacy") or [],
        )
    else:
        base_plan = None
        base = _side_summary(envelope.envelope_id, None, None, None, None, None)
        base["plan"] = None  # explicit: no saved plan to compare against

    # ---- simulated side: local SIM- envelope, never stored/journalled ----
    simulated_envelope = envelope.model_copy(deep=True)
    simulated_envelope.targets = list(req.targets)
    simulated_envelope.status = EnvelopeStatus.APPROVED
    simulated_envelope.envelope_id = f"SIM-{envelope.envelope_id}"
    # SAFETY: simulated_envelope must never reach the envelope store or the
    # journal — this module never calls put_envelope/journal_envelope/save_plan.

    solved_envelope, relaxed = prepare_envelope_for_pool(simulated_envelope, dishes)
    try:
        result = run(solved_envelope, dishes=dishes)
        from backend.optim.composition import improve_meals

        result = improve_meals(result, simulated_envelope, dishes)
        if result.get("meal_complete"):
            solved_envelope, relaxed = simulated_envelope, []
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "optimiser_failed",
                "detail": str(exc),
                "envelope_id": simulated_envelope.envelope_id,
            },
        ) from exc

    # The simulated explanation/adequacy describe the SIMULATED targets.
    simulated_response = map_plan_result(
        result,
        simulated_envelope,
        dishes,
        relaxed_constraints=relaxed,
        solved_envelope=solved_envelope,
    )
    simulated_plan = result.get("plan") or None
    simulated = _side_summary(
        simulated_envelope.envelope_id,
        None,  # simulations never create plan rows
        simulated_response.get("feasible"),
        simulated_response.get("violation_count", 0),
        simulated_response.get("objectives"),
        simulated_response.get("adequacy") or [],
        extra={
            "infeasibility_reason": simulated_response.get("infeasibility_reason"),
            "infeasibility_status": result.get("infeasibility_status"),
            "relaxed_constraints": simulated_response.get("relaxed_constraints") or [],
        },
    )

    # ---- deltas ----
    base_objectives = base.get("objectives")
    sim_objectives = simulated.get("objectives")
    if base_objectives and sim_objectives and simulated.get("feasible"):
        deltas: dict[str, Any] = {
            "cost": round(
                float(sim_objectives["cost"]) - float(base_objectives["cost"]), 4
            ),
            "nutrient_target_deviation": round(
                float(sim_objectives["nutrient_target_deviation"])
                - float(base_objectives["nutrient_target_deviation"]),
                6,
            ),
            "variety": round(
                float(sim_objectives["variety"]) - float(base_objectives["variety"]),
                6,
            ),
            "worst_shortfall_pct": round(
                _pooled_worst_shortfall_pct(simulated.get("adequacy_summary"))
                - _pooled_worst_shortfall_pct(base.get("adequacy_summary")),
                3,
            ),
            "meals_changed": _meals_changed(base_plan, simulated_plan),
        }
    else:
        # Infeasible simulated solve (or no base plan): only the deltas that
        # still make sense are reported; the rest stay null.
        deltas = {
            "cost": None,
            "nutrient_target_deviation": None,
            "variety": None,
            "worst_shortfall_pct": None,
            "meals_changed": None,
        }

    payload = {
        "patient_id": req.patient_id,
        "proposed_targets": [target.model_dump() for target in req.targets],
        "base": base,
        "simulated": simulated,
        "deltas": deltas,
    }

    simulation_id = persistence.save_simulation(
        patient_id=req.patient_id,
        base_envelope_id=envelope.envelope_id,
        proposed_targets=payload["proposed_targets"],
        comparison={"base": base, "simulated": simulated, "deltas": deltas},
    )
    return {**payload, "simulation_id": simulation_id}


@router.get("", summary="Stored what-if simulations for a patient")
def list_simulations(
    patient_id: str = Query(..., description="Patient id"),
) -> dict[str, Any]:
    from backend.app.core import persistence

    simulations = persistence.list_simulations(patient_id)
    return {"count": len(simulations), "simulations": simulations}
