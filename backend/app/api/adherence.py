"""Expose meal logging and historically attributed adherence views."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.adherence import analysis, store
from backend.app.api.patients import get_patient
from backend.app.core import persistence
from backend.app.core.approval_gate import find_latest_envelope_for_patient
from backend.app.models.envelope import NutrientEnvelope
from backend.optim.real_data import load_dishes

router = APIRouter(prefix="/adherence", tags=["adherence"])


class Serving(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    dish_id: str
    quantity: float = Field(default=1, gt=0, le=10)


class MealLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    date: str
    meal: Literal["breakfast", "lunch", "dinner"]
    dish_id: str | None = None
    items: list[Serving] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def one_representation(self):
        # Blank dish IDs could falsely count an empty meal toward day completeness.
        if self.dish_id is not None and not self.dish_id.strip():
            raise ValueError("dish_id must not be blank")
        if self.items is not None and any(
            not item.dish_id.strip() for item in self.items
        ):
            raise ValueError("item dish_id must not be blank")
        if (self.dish_id is None) == (self.items is None):
            raise ValueError("Provide either dish_id or items")
        return self


@lru_cache(maxsize=1)
def _dish_index() -> dict[str, Any]:
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
    """Return inclusive ISO dates ending in UTC."""
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _envelope_notice(envelope: Any) -> tuple[bool, str | None]:
    """Describe the latest envelope's review status, not historical scoring.

    Return ``(False, None)`` for APPROVED status, otherwise ``(True, notice)``.
    Logged days still use the approval effective on their consumption date.
    """
    status = envelope.status.value
    if status == "APPROVED":
        return False, None
    return True, (
        f"Envelope status is {status}; comparisons below are informational "
        "only — this envelope has not been approved by a clinician and must "
        "not be treated as clinical guidance."
    )


def _resolve_day_envelopes(
    patient_id: str, dates: Iterable[str]
) -> tuple[dict[str, NutrientEnvelope | None], list[str]]:
    """Resolve historical approval coverage for each distinct logged date.

    Only approvals effective on or before consumption qualify. Return the
    date-to-envelope mapping and sorted uncovered dates. Uncovered dates map
    to ``None`` rather than retroactively using current targets.
    """
    assignment: dict[str, NutrientEnvelope | None] = {}
    unattributed: list[str] = []
    for day in sorted(set(dates)):
        envelope = persistence.envelope_effective_at(patient_id, day)
        assignment[day] = envelope
        if envelope is None:
            unattributed.append(day)
    return assignment, unattributed


def attributed_analysis(
    patient_id: str,
    logs: list[dict[str, Any]],
    dish_by_id: Any,
    *,
    with_series: bool,
) -> dict[str, Any]:
    """Analyse covered logs separately for each effective envelope version.

    Return a dictionary containing:

    * ``groups``: ordered by first covered date. Each group holds its approved
      ``envelope``, ``dates``, ``logs``, analysis ``result``, and series-prefix
      ``label``. Results contain days and aggregate statistics. ``with_series``
      also adds deviation series and trend flags.
    * ``unattributed_days``: sorted uncovered dates, excluded from target scoring.
    * ``latest``: the latest proposal, or ``None``. This is review-status metadata,
      not the envelope used to score historical logs.

    Labels use envelope IDs. If an ID spans multiple versions in the window,
    every label includes ``::v<version>`` to disambiguate series and flags.
    """
    assignment, unattributed = _resolve_day_envelopes(
        patient_id, (log["date"] for log in logs)
    )
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for day in sorted(assignment):
        envelope = assignment[day]
        if envelope is None:
            continue
        key = (envelope.envelope_id, envelope.version)
        group = groups.setdefault(
            key, {"envelope": envelope, "dates": [], "logs": []}
        )
        group["dates"].append(day)
    for log in logs:
        envelope = assignment.get(log["date"])
        if envelope is None:
            continue
        groups[(envelope.envelope_id, envelope.version)]["logs"].append(log)

    ordered = sorted(
        groups.values(),
        key=lambda g: (g["dates"][0], g["envelope"].envelope_id, int(g["envelope"].version)),
    )
    id_count: dict[str, int] = {}
    for group in ordered:
        eid = group["envelope"].envelope_id
        id_count[eid] = id_count.get(eid, 0) + 1
    ambiguous = any(count > 1 for count in id_count.values())
    for group in ordered:
        eid = group["envelope"].envelope_id
        group["label"] = (
            f"{eid}::v{int(group['envelope'].version)}" if ambiguous else eid
        )
        if with_series:
            group["result"] = analysis.analyse_patient(
                group["logs"], group["envelope"], dish_by_id
            )
        else:
            ranged = analysis.analyse_range(group["logs"], group["envelope"], dish_by_id)
            group["result"] = {
                "days": ranged["days"],
                "aggregate": ranged["aggregate"],
            }
    return {
        "groups": ordered,
        "unattributed_days": unattributed,
        "latest": find_latest_envelope_for_patient(patient_id),
    }


def _versions_used(attributed: dict[str, Any]) -> list[dict[str, Any]]:
    """List the envelope versions and logged dates actually used for scoring."""
    return [
        {
            "envelope_id": group["envelope"].envelope_id,
            "version": int(group["envelope"].version),
            "status": group["envelope"].status.value,
            "days": list(group["dates"]),
        }
        for group in attributed["groups"]
    ]


def _flag_sort_key(flag: dict[str, Any]) -> tuple[int, float]:
    order = {"worsening": 0, "improving": 1}
    return (order.get(flag["direction"], 2), -abs(flag["slope_pct_per_day"]))


@router.post("/log", status_code=201, summary="Log an actual meal")
def log_meal(req: MealLogRequest) -> dict[str, Any]:
    """Save or replace a patient's logged meal for one date and meal slot."""
    _require_patient(req.patient_id)
    dish_ids = [item.dish_id for item in req.items] if req.items else [req.dish_id]
    missing = next((did for did in dish_ids if did not in _dish_index()), None)
    if missing is not None:
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": missing},
        )
    try:
        date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_date", "date": req.date},
        )
    return store.put_log(req.patient_id, date.fromisoformat(req.date).isoformat(), req.meal, dish_ids[0],
                         items=[item.model_dump() for item in req.items] if req.items else None)


@router.get("/{patient_id}/summary", summary="Adherence summary vs the envelope")
def adherence_summary(
    patient_id: str,
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    """Summarize meals against approvals effective on each logged date.

    Uncovered dates are listed without target scoring. Top-level envelope
    identity and review notices describe the latest proposal, not each day.
    """
    _require_patient(patient_id)
    envelope = _latest_envelope_or_404(patient_id)
    informational_only, notice = _envelope_notice(envelope)

    start, end = _date_window(days)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    attributed = attributed_analysis(patient_id, logs, _dish_index(), with_series=False)
    groups = attributed["groups"]

    if len(groups) <= 1:
        # Retain legacy response fields for zero or one covered envelope version.
        if groups:
            result = groups[0]["result"]
        else:
            ranged = analysis.analyse_range([], envelope, _dish_index())
            result = {"days": ranged["days"], "aggregate": ranged["aggregate"]}
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
            "envelope_versions_used": _versions_used(attributed),
            "unattributed_days": attributed["unattributed_days"],
        }

    # Aggregate historical classifications without rescoring against current targets.
    merged_days = sorted(
        (day for group in groups for day in group["result"]["days"]),
        key=lambda day: day["date"],
    )
    aggregate = analysis.aggregate_days(merged_days)
    return {
        "patient_id": patient_id,
        "envelope_id": envelope.envelope_id,
        "envelope_status": envelope.status.value,
        "informational_only": informational_only,
        "notice": notice,
        "window": {"start": start, "end": end, "days": days},
        "days_logged": aggregate["days_logged"],
        "days": merged_days,
        "aggregate": aggregate,
        "envelope_versions_used": _versions_used(attributed),
        "unattributed_days": attributed["unattributed_days"],
    }


@router.get("/{patient_id}/deviation", summary="Deviation time-series + trend flags")
def adherence_deviation(
    patient_id: str,
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    """Return historically attributed deviations and complete-day trend flags.

    Top-level envelope identity and review notices describe the latest proposal.
    Uncovered dates are listed without deviation scoring. Series prefixes
    distinguish covered envelope versions only when the window spans groups.
    """
    _require_patient(patient_id)
    envelope = _latest_envelope_or_404(patient_id)
    informational_only, notice = _envelope_notice(envelope)

    start, end = _date_window(days)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    attributed = attributed_analysis(patient_id, logs, _dish_index(), with_series=True)
    groups = attributed["groups"]

    if len(groups) <= 1:
        # Keep legacy series keys unprefixed while adding envelope identity to flags.
        if groups:
            result = groups[0]["result"]
            flags = [
                dict(
                    flag,
                    envelope_id=groups[0]["envelope"].envelope_id,
                    envelope_version=int(groups[0]["envelope"].version),
                )
                for flag in result["flags"]
            ]
        else:
            result = analysis.analyse_patient([], envelope, _dish_index())
            flags = [
                dict(flag, envelope_id=envelope.envelope_id, envelope_version=int(envelope.version))
                for flag in result["flags"]
            ]
        return {
            "patient_id": patient_id,
            "envelope_id": envelope.envelope_id,
            "envelope_status": envelope.status.value,
            "informational_only": informational_only,
            "notice": notice,
            "window": {"start": start, "end": end, "days": days},
            "series": result["series"],
            "flags": flags,
            "envelope_versions_used": _versions_used(attributed),
            "unattributed_days": attributed["unattributed_days"],
        }

    # Prefix flags exactly like series so each flag resolves to its historical series.
    series: dict[str, dict[str, Any]] = {}
    merged_flags: list[dict[str, Any]] = []
    for group in groups:
        label = group["label"]
        for key, value in group["result"]["series"].items():
            series[f"{label}::{key}"] = value
        for flag in group["result"]["flags"]:
            merged_flags.append(
                dict(
                    flag,
                    series_key=f"{label}::{flag['series_key']}",
                    envelope_id=group["envelope"].envelope_id,
                    envelope_version=int(group["envelope"].version),
                )
            )
    merged_flags.sort(key=_flag_sort_key)
    return {
        "patient_id": patient_id,
        "envelope_id": envelope.envelope_id,
        "envelope_status": envelope.status.value,
        "informational_only": informational_only,
        "notice": notice,
        "window": {"start": start, "end": end, "days": days},
        "series": series,
        "flags": merged_flags,
        "envelope_versions_used": _versions_used(attributed),
        "unattributed_days": attributed["unattributed_days"],
    }
