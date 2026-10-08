"""Mining endpoints (deterministic, read-only).

* ``GET /mining/trends`` — longitudinal K+/PO4 trend flags over
  ``data/patients.json`` (``backend.mining.trends.detect_trends``).
* ``GET /mining/substitutions?dish_id=...&k=3`` — v2 substitution suggestions
  from the dish database (``backend.mining.substitutions.suggest_substitutions``).
  With the optional ``patient_id`` query param the suggestions become
  patient-aware meal swaps (Milestone 2, review finding E): candidates are
  filtered against the patient's envelope exclusions and validated with the
  canonical evaluator against every plan day containing the dish, with
  per-nutrient day deltas and cost deltas attached.
* ``POST /mining/swaps/apply`` — apply a validated swap: replaces EVERY
  occurrence of the dish in the patient's saved plan, refuses hard-violating
  swaps (422), and persists the result as a NEW plan row with a
  ``derived_from`` lineage field (minimal "meal locking").
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

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
PATIENTS_FILE = _REPO_ROOT / "data" / "patients.json"


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
    """dish_id -> Dish, from the real dataset (cached per process)."""
    return {dish.dish_id: dish for dish in load_dishes()}


def _envelope_notice(envelope: Any) -> tuple[bool, Optional[str]]:
    """(informational_only, notice) — mirrors the adherence endpoints."""
    status = envelope.status.value
    if status == "APPROVED":
        return False, None
    return True, (
        f"Envelope status is {status}; comparisons below are informational "
        "only — this envelope has not been approved by a clinician and must "
        "not be treated as clinical guidance."
    )


def _json_safe_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSON has no Infinity — blank out non-finite magnitudes."""
    safe = []
    for violation in violations or []:
        cleaned = dict(violation)
        for key in ("amount", "actual", "limit"):
            value = cleaned.get(key)
            if isinstance(value, float) and (
                value != value or value in (float("inf"), float("-inf"))
            ):
                cleaned[key] = None
        safe.append(cleaned)
    return safe


@router.get("/trends", summary="Rising K+/PO4 trend flags across the cohort")
def trends() -> dict:
    from backend.app.api.patients import get_patient, list_patient_ids

    flags = detect_trends([get_patient(pid) for pid in list_patient_ids()])
    return {"count": len(flags), "flags": flags}


@router.get("/substitutions", summary="Healthier substitute dishes for a dish")
def substitutions(
    dish_id: str = Query(..., description="Dish id from data/dishes.json"),
    k: int = Query(3, ge=1, le=10, description="Max suggestions"),
    patient_id: Optional[str] = Query(
        default=None,
        description=(
            "When given, rank + validate suggestions against this patient's "
            "latest envelope and saved plan (patient-aware meal swaps)."
        ),
    ),
    plan_id: Optional[str] = Query(default=None, description="Exact saved plan to preview"),
) -> dict:
    if patient_id is None:
        # Legacy behaviour, byte-identical: generic similarity ranking only.
        try:
            results = suggest_substitutions(dish_id, k=k, version=2)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail={"error": "dish_not_found", "dish_id": dish_id},
            )
        return {"dish_id": dish_id, "k": k, "substitutions": results}

    # ---- patient-aware meal swaps (Milestone 2, review finding E) ----
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
    """Body for ``POST /mining/swaps/apply``."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    dish_id: str
    replacement_dish_id: str
    plan_id: Optional[str] = None


@router.post("/swaps/apply", summary="Apply a patient-aware meal swap")
def apply_swap(req: SwapApplyRequest) -> dict[str, Any]:
    """Replace every occurrence of ``dish_id`` in the patient's saved plan.

    The modified plan is validated with the canonical evaluator against the
    APPROVED envelope; a hard violation (MAX ceiling, exclusion, membership)
    answers 422 and nothing is persisted.  A valid swap is saved as a NEW
    plan row whose document carries ``derived_from`` (the source plan id) so
    the lineage stays auditable.  The source plan is never mutated.
    """
    from backend.app.core import persistence
    from backend.app.api.plans import _persist_plan

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
        # Rendered as the documented 409 {"error": "envelope_not_approved"}.
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

    # Re-map through the canonical frontend mapper so the new document keeps
    # the same shape as a generated plan (days/totals/adequacy/explanation),
    # scored against the ORIGINAL approved envelope.
    document = map_plan_result(
        {
            "plan": outcome.modified_plan,
            "feasible": True,
            "violation_count": 0,
            "objectives": outcome.objectives,
            "envelope_id": envelope.envelope_id,
            "patient_id": envelope.patient_id,
            "meal_encoding": plan_document.get("meal_encoding", "single_dish"),
            "meal_complete": plan_document.get("meal_complete", False),
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

    _persist_plan(document, envelope)
    return document
