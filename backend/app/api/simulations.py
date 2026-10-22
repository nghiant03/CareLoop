from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.core.approval_gate import (
    EnvelopeNotApprovedError,
    find_latest_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result, plan_meals
from backend.app.models.envelope import EnvelopeStatus, NutrientConstraint
from backend.mining.patient_swaps import plan_from_document
from backend.optim.problem import evaluate
from backend.optim.real_data import load_dishes

router = APIRouter(prefix="/simulations", tags=["simulations"])


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    targets: list[NutrientConstraint]


def _worst_aim_deviation_pct(adequacy: list[dict[str, Any]] | None) -> float:
    """Legacy shortfall fields include absolute TARGET deviations."""
    values = [
        float(entry.get("shortfall_pct") or 0.0)
        for entry in (adequacy or [])
        if entry.get("shortfall_pct") is not None
    ]
    return round(max(values), 3) if values else 0.0


def _meals_changed(base_plan, simulated_plan) -> int | None:
    """Ignore dish order but preserve repeated dishes."""
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
    plan_id: str | None,
    feasible: bool | None,
    violation_count: int | None,
    objectives: dict[str, float] | None,
    adequacy_summary: list[dict[str, Any]] | None,
    extra: dict[str, Any] | None = None,
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
    """Save a comparison without changing live envelopes or plans. Infeasible comparisons still return success."""
    from backend.app.core import persistence

    envelope = find_latest_envelope_for_patient(req.patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": req.patient_id},
        )
    if not envelope.is_ready_for_optimisation():
        raise EnvelopeNotApprovedError(envelope)

    try:
        dishes = load_dishes()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"error": "dish_database_unavailable"}) from exc

    plan_summary = persistence.latest_plan_for_patient(req.patient_id)
    base_plan: list | None = None
    if plan_summary is not None:
        plan_document = persistence.get_plan(plan_summary["plan_id"]) or {}
        if plan_document.get("days"):
            base_plan = plan_from_document(plan_document)
    if base_plan and plan_summary is not None:
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
        base["plan"] = None

    simulated_envelope = envelope.model_copy(deep=True)
    simulated_envelope.targets = list(req.targets)
    simulated_envelope.status = EnvelopeStatus.APPROVED
    simulated_envelope.envelope_id = f"SIM-{envelope.envelope_id}"

    try:
        outcome = plan_meals(simulated_envelope, dishes)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "optimiser_failed",
                "detail": str(exc),
                "envelope_id": simulated_envelope.envelope_id,
            },
        ) from exc

    simulated_response = map_plan_result(
        outcome.result,
        simulated_envelope,
        dishes,
        relaxed_constraints=outcome.relaxed_constraints,
        solved_envelope=outcome.solved_envelope,
    )
    result = outcome.result
    simulated_plan = result.get("plan") or None
    simulated = _side_summary(
        simulated_envelope.envelope_id,
        None,
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
                _worst_aim_deviation_pct(simulated.get("adequacy_summary"))
                - _worst_aim_deviation_pct(base.get("adequacy_summary")),
                3,
            ),
            "meals_changed": _meals_changed(base_plan, simulated_plan),
        }
    else:
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
