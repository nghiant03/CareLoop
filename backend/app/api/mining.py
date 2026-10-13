"""Expose lab trend flags, dish substitutions, and patient-aware meal swaps."""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.core.approval_gate import (
    EnvelopeNotApprovedError,
    find_latest_envelope_for_patient,
)
from backend.app.core.plan_service import map_plan_result
from backend.mining.patient_swaps import (
    DishNotInPlanError,
    apply_patient_swap,
    patient_substitutions,
)
from backend.mining.substitutions import suggest_substitutions
from backend.mining.trends import detect_trends
from backend.optim.real_data import load_dishes

logger = logging.getLogger("careloop.mining")

router = APIRouter(prefix="/mining", tags=["mining"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

PATIENTS_FILE = dataset_path("patients.json")


def _load_patients() -> list[dict]:
    if not PATIENTS_FILE.exists():
        return []
    try:
        raw = json.loads(PATIENTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("patients", [])
    return [p for p in raw if isinstance(p, dict)]


@lru_cache(maxsize=1)
def _dish_index() -> dict[str, Any]:
    """Return catalogue dishes keyed by ID, caching the index within the process."""
    return {dish.dish_id: dish for dish in load_dishes()}


def _envelope_notice(envelope: Any) -> tuple[bool, str | None]:
    """Return whether comparisons are informational-only and any approval warning."""
    status = envelope.status.value
    if status == "APPROVED":
        return False, None
    return True, (
        f"Envelope status is {status}; comparisons below are informational "
        "only — this envelope has not been approved by a clinician and must "
        "not be treated as clinical guidance."
    )


def _json_safe_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies with non-finite violation magnitudes replaced by ``None``.

    Only float values in ``amount``, ``actual``, and ``limit`` are sanitized.
    Leave input rows and other fields unchanged.
    """
    safe = []
    for violation in violations or []:
        cleaned = dict(violation)
        for key in ("amount", "actual", "limit"):
            value = cleaned.get(key)
            if isinstance(value, float) and (
                math.isnan(value) or math.isinf(value)
            ):
                cleaned[key] = None
        safe.append(cleaned)
    return safe


@router.get("/trends", summary="Rising K+/PO4 trend flags across the cohort")
def trends() -> dict:
    """Return cohort potassium/phosphate lab flags in ``flags`` and their ``count``."""
    from backend.app.api.patients import get_patient, list_patient_ids

    flags = detect_trends(
        [p for p in (get_patient(pid) for pid in list_patient_ids()) if p is not None]
    )
    return {"count": len(flags), "flags": flags}


@router.get("/substitutions", summary="Healthier substitute dishes for a dish")
def substitutions(
    dish_id: str = Query(..., description="Dish id from data/dishes.json"),
    k: int = Query(3, ge=1, le=10, description="Max suggestions"),
    patient_id: str | None = Query(
        default=None,
        description=(
            "When given, rank + validate suggestions against this patient's "
            "latest envelope and saved plan (patient-aware meal swaps)."
        ),
    ),
    plan_id: str | None = Query(default=None, description="Exact saved plan to preview"),
) -> dict:
    """Return up to ``k`` generic substitutions or patient-specific swap previews.

    Omit ``patient_id`` for generic suggestions. ``plan_id`` is then ignored.
    Patient previews use the latest envelope and the selected or latest saved plan.
    They satisfy whole-plan hard constraints and meal roles. Results include
    affected days, nutrient deltas, and cost deltas. Unapproved previews are informational
    and do not authorize applying a swap.

    Return HTTP 404 for unknown dishes, missing envelopes, or selected plans that
    are missing or belong to another patient. Return HTTP 409 when no latest plan
    exists or the source dish is absent from the plan.
    """
    if patient_id is None:
        try:
            results = suggest_substitutions(dish_id, k=k, version=2)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail={"error": "dish_not_found", "dish_id": dish_id},
            )
        return {"dish_id": dish_id, "k": k, "substitutions": results}

    from backend.app.core import persistence

    if dish_id not in _dish_index():
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": dish_id},
        )

    envelope = find_latest_envelope_for_patient(patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": patient_id},
        )
    informational_only, notice = _envelope_notice(envelope)

    summary = ({"plan_id": plan_id} if plan_id else persistence.latest_plan_for_patient(patient_id))
    if summary is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "plan_context_required",
                "message": (
                    "Generate a meal plan for this patient first so swaps can "
                    "be validated against their actual day."
                ),
            },
        )
    plan_document = persistence.get_plan(summary["plan_id"])
    if plan_document is None or plan_document.get("patient_id") != patient_id:
        raise HTTPException(status_code=404, detail={"error": "plan_not_found"})

    try:
        validated = patient_substitutions(
            dish_id, k, envelope, plan_document or {}, load_dishes()
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": dish_id},
        )
    except DishNotInPlanError as exc:
        raise HTTPException(status_code=409, detail={"error": "dish_not_in_plan", "message": str(exc)})

    return {
        "dish_id": dish_id,
        "k": k,
        "patient_id": patient_id,
        "plan_id": summary["plan_id"],
        "informational_only": informational_only,
        "notice": notice,
        "affected_days": validated["affected_days"],
        "substitutions": validated["substitutions"],
    }


class SwapApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    dish_id: str
    replacement_dish_id: str
    plan_id: str | None = None


@router.post("/swaps/apply", summary="Apply a patient-aware meal swap")
def apply_swap(req: SwapApplyRequest) -> dict[str, Any]:
    """Return a derived plan with every ``dish_id`` occurrence replaced.

    Use the selected or latest saved plan without changing the source. The latest
    envelope must be approved, scope-eligible, and have targets. Whole-plan hard
    constraint or meal-role violations return HTTP 422 without saving a new plan.

    Return HTTP 404 for unknown dishes, missing envelopes, or selected plans that
    are missing or belong to another patient. Return HTTP 409 when the envelope
    is not ready, no latest plan exists, or the source dish is absent from the plan.

    Results include ``derived_from`` and ``applied_swap`` even if saving fails.
    A missing response ``plan_id`` does not prove the derived plan was not saved.
    """
    from backend.app.core import persistence
    from backend.app.core.plan_storage import try_save_plan_document

    for dish_id in (req.dish_id, req.replacement_dish_id):
        if dish_id not in _dish_index():
            raise HTTPException(
                status_code=404,
                detail={"error": "dish_not_found", "dish_id": dish_id},
            )

    envelope = find_latest_envelope_for_patient(req.patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": req.patient_id},
        )
    if not envelope.is_ready_for_optimisation():
        raise EnvelopeNotApprovedError(envelope)

    if req.plan_id:
        source_plan_id = req.plan_id
        plan_document = persistence.get_plan(source_plan_id)
        if plan_document is None or plan_document.get("patient_id") != req.patient_id:
            raise HTTPException(
                status_code=404,
                detail={"error": "plan_not_found", "plan_id": source_plan_id},
            )
    else:
        summary = persistence.latest_plan_for_patient(req.patient_id)
        if summary is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "plan_context_required",
                    "message": (
                        "Generate a meal plan for this patient first so swaps can "
                        "be validated against their actual day."
                    ),
                },
            )
        source_plan_id = summary["plan_id"]
        plan_document = persistence.get_plan(source_plan_id)

    try:
        outcome = apply_patient_swap(
            req.dish_id,
            req.replacement_dish_id,
            plan_document or {},
            envelope,
            load_dishes(),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": str(exc)},
        )
    except DishNotInPlanError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "dish_not_in_plan", "message": str(exc)},
        )

    if outcome.violations:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "swap_violates_constraints",
                "violations": _json_safe_violations(outcome.violations),
            },
        )

    # Reuse generation mapping to preserve the response shape and original-aim adequacy scoring.
    document = map_plan_result(
        {
            "plan": outcome.modified_plan,
            "feasible": True,
            "violation_count": 0,
            "objectives": outcome.objectives,
            "envelope_id": envelope.envelope_id,
            "patient_id": envelope.patient_id,
            "meal_encoding": (plan_document or {}).get("meal_encoding", "single_dish"),
            "meal_complete": (plan_document or {}).get("meal_complete", False),
        },
        envelope,
        load_dishes(),
    )
    document["engine"] = "patient_swap"
    document["derived_from"] = source_plan_id
    document["applied_swap"] = {
        "dish_id": req.dish_id,
        "replacement_dish_id": req.replacement_dish_id,
        "affected_days": outcome.affected_days,
        "occurrences_replaced": outcome.occurrences_replaced,
    }

    try_save_plan_document(document, envelope)
    return document
