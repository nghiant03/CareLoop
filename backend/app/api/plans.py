"""Meal-plan endpoint.

``POST /plans`` is gated on an APPROVED envelope. Week 1 dispatches to
``backend.optim.api.run`` which delegates to ``spike_pymoo`` (or its
NSGA-II fallback when pymoo is unavailable).
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.approval_gate import (
    PlanRequest,
    require_approved_envelope_for_patient,
)
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


@router.post("", summary="Generate a meal plan from an APPROVED envelope")
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
    return run(envelope)
