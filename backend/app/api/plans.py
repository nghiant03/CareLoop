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
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.approval_gate import (
    PlanRequest,
    require_approved_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result, prepare_envelope_for_pool
from backend.app.models.envelope import NutrientEnvelope

logger = logging.getLogger("careloop.plans")

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


def _kb_version() -> str:
    """Version tag of the loaded knowledge base (fallback: node count)."""
    try:
        from backend.app.core.kb_loader import get_kb

        stats = get_kb().stats()
        version = stats.get("current_version")
        if version:
            return str(version)
        return f"nodes:{sum(stats.get('node_counts', {}).values())}"
    except Exception as exc:  # pragma: no cover - missing dataset
        logger.warning("knowledge base version unavailable: %s", exc)
        return "unknown"


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
        from backend.optim.composition import improve_meals

        result = improve_meals(result, envelope, dishes)
        if result.get("meal_complete"):
            solved_envelope, relaxed = envelope, []
    except Exception as exc:  # optimiser guard / unexpected failure
        raise HTTPException(
            status_code=502,
            detail={
                "error": "optimiser_failed",
                "detail": str(exc),
                "envelope_id": envelope.envelope_id,
            },
        ) from exc

    response = map_plan_result(
        result, envelope, dishes, relaxed_constraints=relaxed, solved_envelope=solved_envelope
    )

    # Persist the plan (Milestone 3): keyed on the ORIGINAL approved envelope's
    # id/version, not the MIN-relaxed copy the optimiser actually solved.
    _persist_plan(response, envelope)

    return response


def _persist_plan(response: dict[str, Any], envelope: NutrientEnvelope) -> None:
    """Store the mapped plan response; adds ``plan_id``/``saved_at`` in place.

    Persistence is best-effort: a storage failure must not lose the freshly
    generated plan, so it is logged and the response is returned unsaved.
    """
    try:
        from backend.app.core import persistence
        from hashlib import sha256
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        response["source_hashes"] = {
            name: sha256((root / name).read_bytes()).hexdigest()
            for name in ("data/dishes.json", "rules/rules.json")
        }
        response["approved_envelope"] = envelope.model_dump(mode="json", by_alias=True)

        plan_id = persistence.save_plan(
            patient_id=str(response.get("patient_id") or envelope.patient_id),
            envelope_id=envelope.envelope_id,
            envelope_version=envelope.version,
            engine=response.get("engine"),
            feasible=bool(response.get("feasible")),
            violation_count=int(response.get("violation_count") or 0),
            objectives=response.get("objectives"),
            days=response.get("days"),
            adequacy=response.get("adequacy"),
            kb_version=_kb_version(),
            document=response,
        )
        stored = persistence.get_plan(plan_id)
        response["plan_id"] = plan_id
        response["saved_at"] = (
            stored["saved_at"] if stored and "saved_at" in stored else None
        )
    except Exception as exc:  # pragma: no cover - depends on storage backend
        logger.warning("plan persistence failed: %s", exc)


@router.get("", summary="List stored plan summaries")
def list_plans_endpoint(
    patient_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Stored plan summaries (newest first), optionally for one patient."""
    from backend.app.core import persistence

    plans = persistence.list_plans(patient_id)
    return {"count": len(plans), "plans": plans}


@router.get("/{plan_id}", summary="Get a stored plan by id (survives restart)")
def read_plan(plan_id: str) -> dict[str, Any]:
    """Full stored plan document; 404 ``plan_not_found`` when unknown."""
    from backend.app.core import persistence

    plan = persistence.get_plan(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "plan_not_found", "plan_id": plan_id},
        )
    return plan
