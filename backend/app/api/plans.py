"""Meal-plan endpoint.

``POST /plans`` is gated on an APPROVED envelope (the approval-gate dependency
keeps the documented 409 body). The approved envelope is handed to
``backend.optim.api.run`` (NSGA-II + hard feasibility guarantee). Before
solving, unreachable MIN floors are relaxed to the achievable pool bound
(see ``core/plan_service.py`` — disclosed in the response as
``relaxed_constraints``). The optimiser result is mapped to the frontend
contract: ``days[]`` with ``slots[]`` + ``totals[]`` vs targets, plus the
plain-language patient explanation panel payload. An additive top-level
``adequacy[]`` array scores delivery against the ORIGINAL approved envelope
(one entry per MIN/TARGET constraint; MAX ceilings excluded) so shortfalls
against the approved aims stay visible even when a floor was relaxed.

An infeasible pool returns HTTP 200 with ``feasible: false`` and
``infeasibility_reason`` (the UI renders the reason); the gate still answers
409. ``POST /plans`` body: ``{"patient_id": "..."}``.
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.approval_gate import (
    PlanRequest,
    require_approved_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result, prepare_envelope_for_pool
from backend.app.models.envelope import NutrientEnvelope

router = APIRouter(prefix="/plans", tags=["plans"])


def _load_optimiser():
    """Return ``backend.optim.api`` (the API adapter). Falls back to None."""
    try:
        return importlib.import_module("backend.optim.api")
    except ModuleNotFoundError:
        try:
            return importlib.import_module("backend.optim.spike_pymoo")
        except ModuleNotFoundError:
            return None


def _load_dishes():
    try:
        real_data = importlib.import_module("backend.optim.real_data")
        return real_data.load_dishes()
    except Exception:  # pragma: no cover - dataset missing
        return None


@router.post("", summary="Generate a 7-day meal plan from an APPROVED envelope")
def create_plan(
    req: PlanRequest,
    envelope: NutrientEnvelope = Depends(require_approved_envelope_for_patient),
):
    optimiser = _load_optimiser()
    if optimiser is None:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "optimiser_not_implemented",
                "message": "backend.optim is not available yet (Lane B, Week 1).",
                "envelope_id": envelope.envelope_id,
            },
        )

    run = getattr(optimiser, "run", None) or getattr(optimiser, "optimise", None)
    if run is None:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "optimiser_contract_missing",
                "message": "backend.optim exposes no run()/optimise().",
            },
        )

    dishes = _load_dishes()
    if dishes is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "dish_database_unavailable",
                "message": "data/dishes.json could not be loaded.",
            },
        )

    solved_envelope, relaxed = prepare_envelope_for_pool(envelope, dishes)
    try:
        result = run(solved_envelope, dishes=dishes)
    except Exception as exc:  # optimiser guard / unexpected failure
        raise HTTPException(
            status_code=502,
            detail={
                "error": "optimiser_failed",
                "detail": str(exc),
                "envelope_id": envelope.envelope_id,
            },
        ) from exc

    return map_plan_result(
        result, envelope, dishes, relaxed_constraints=relaxed, solved_envelope=solved_envelope
    )