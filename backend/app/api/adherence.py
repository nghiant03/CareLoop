"""Adherence endpoints — the "loop" in CareLoop.

Patients log what they actually ate (``POST /adherence/log``); the logged
meals are measured against the patient's latest nutrient envelope and fed back
as per-day totals, hard-violation / soft-gap classifications, aggregate stats
(``GET .../summary``) and a deviation time-series with trend flags
(``GET .../deviation``).

Envelope handling mirrors ``/chat``: the *latest* envelope for the patient is
used regardless of status, but when it is not ``APPROVED`` the response carries
a clear ``envelope_status`` notice and ``informational_only: true`` — the
approval gate is never bypassed, comparisons are simply labelled as
informational.
"""

from __future__ import annotations

from datetime import date as date_type, timedelta
from functools import lru_cache
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.adherence import analysis, store
from backend.app.api.patients import get_patient
from backend.app.core.approval_gate import find_latest_envelope_for_patient
from backend.optim.real_data import load_dishes

router = APIRouter(prefix="/adherence", tags=["adherence"])


class MealLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    date: str
    meal: Literal["breakfast", "lunch", "dinner"]
    dish_id: str


@lru_cache(maxsize=1)
def _dish_index() -> dict[str, Any]:
    """dish_id -> Dish, from the real dataset (cached per process)."""
    return {dish.dish_id: dish for dish in load_dishes()}


def _require_patient(patient_id: str) -> dict[str, Any]:
    patient = get_patient(patient_id)
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )
    return patient


def _latest_envelope_or_404(patient_id: str) -> Any:
    envelope = find_latest_envelope_for_patient(patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": patient_id},
        )
    return envelope


def _date_window(days: int) -> tuple[str, str]:
    """Inclusive ISO date window: the last ``days`` days ending today (UTC)."""
    end = date_type.today()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _envelope_notice(envelope: Any) -> tuple[bool, Optional[str]]:
    """(informational_only, notice) — mirrors chat's any-status behaviour."""
    status = envelope.status.value
    if status == "APPROVED":
        return False, None
    return True, (
        f"Envelope status is {status}; comparisons below are informational "
        "only — this envelope has not been approved by a clinician and must "
        "not be treated as clinical guidance."
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/log", status_code=201, summary="Log an actual meal")
def log_meal(req: MealLogRequest) -> dict[str, Any]:
    _require_patient(req.patient_id)
    if req.dish_id not in _dish_index():
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": req.dish_id},
        )
    try:
        date_type.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_date", "date": req.date},
        )
    return store.put_log(req.patient_id, req.date, req.meal, req.dish_id)


@router.get("/{patient_id}/summary", summary="Adherence summary vs the envelope")
def adherence_summary(
    patient_id: str,
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    _require_patient(patient_id)
    envelope = _latest_envelope_or_404(patient_id)
    informational_only, notice = _envelope_notice(envelope)

    start, end = _date_window(days)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    result = analysis.analyse_range(logs, envelope, _dish_index())

    return {
        "patient_id": patient_id,
        "envelope_id": envelope.envelope_id,
        "envelope_status": envelope.status.value,
        "informational_only": informational_only,
        "notice": notice,
        "window": {"start": start, "end": end, "days": days},
        "days_logged": result["aggregate"]["days_logged"],
        "days": result["days"],
        "aggregate": result["aggregate"],
    }


@router.get("/{patient_id}/deviation", summary="Deviation time-series + trend flags")
def adherence_deviation(
    patient_id: str,
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    _require_patient(patient_id)
    envelope = _latest_envelope_or_404(patient_id)
    informational_only, notice = _envelope_notice(envelope)

    start, end = _date_window(days)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    result = analysis.analyse_patient(logs, envelope, _dish_index())

    return {
        "patient_id": patient_id,
        "envelope_id": envelope.envelope_id,
        "envelope_status": envelope.status.value,
        "informational_only": informational_only,
        "notice": notice,
        "window": {"start": start, "end": end, "days": days},
        "series": result["series"],
        "flags": result["flags"],
    }