"""Generate and retrieve meal plans, gated on an approved envelope for generation."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core import persistence
from backend.app.core.approval_gate import (
    PlanRequest,
    require_approved_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result, plan_meals
from backend.app.core.plan_storage import try_save_plan_document
from backend.app.models.envelope import NutrientEnvelope
from backend.optim.real_data import load_dishes

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("", summary="Generate a 7-day meal plan from an APPROVED envelope")
def create_plan(
    req: PlanRequest,
    envelope: NutrientEnvelope = Depends(require_approved_envelope_for_patient),
):
    try:
        dishes = load_dishes()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"error": "dish_database_unavailable"}) from exc
    try:
        outcome = plan_meals(envelope, dishes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "optimiser_failed", "detail": str(exc), "envelope_id": envelope.envelope_id,
        }) from exc
    response = map_plan_result(
        outcome.result, envelope, dishes, relaxed_constraints=outcome.relaxed_constraints,
        solved_envelope=outcome.solved_envelope,
    )
    try_save_plan_document(response, envelope)
    return response


@router.get("", summary="List stored plan summaries")
def list_plans_endpoint(patient_id: str | None = Query(default=None)) -> dict[str, Any]:
    plans = persistence.list_plans(patient_id)
    return {"count": len(plans), "plans": plans}


@router.get("/{plan_id}", summary="Get a stored plan by id (survives restart)")
def read_plan(plan_id: str) -> dict[str, Any]:
    plan = persistence.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    return plan
