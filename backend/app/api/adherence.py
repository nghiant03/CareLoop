"""Adherence endpoints — the "loop" in CareLoop.

Patients log what they actually ate (``POST /adherence/log``); the logged
meals are measured against the patient's nutrient envelopes and fed back
as per-day totals, hard-violation / soft-gap classifications, aggregate stats
(``GET .../summary``) and a deviation time-series with trend flags
(``GET .../deviation``).

The latest envelope supplies top-level status metadata and an informational
notice when it is unapproved. It does not supply historical comparison targets.
See ``docs/ARCHITECTURE.md`` for the approval-coverage contract.

Envelope-version attribution (Milestone 3)
------------------------------------------
History is evaluated against the envelope that was **effective on each
consumption date**, not blindly against the latest one. Each logged date is
resolved through ``persistence.envelope_effective_at`` (the durable envelope
journal). Dates without approval coverage remain unattributed; there is no
fallback to current targets. Covered days are grouped by the resolving envelope
(identity *and* version) and analysed per group:

* **Single-group responses** keep the exact legacy shape (plain series keys,
  plain flags) — only additive fields are new, so existing consumers are
  unaffected.
* **Multi-group responses** merge the per-group results: day rows keep their
  per-group classification, deviation series keys are prefixed
  ``"<envelope_id>::<series_key>"`` (disambiguated to
  ``"<envelope_id>::v<version>::<series_key>"`` uniformly for all groups when
  one window spans multiple *versions of the same envelope id*), and flags are
  merged with an ``envelope_id`` (and ``envelope_version``) stamp.

Every analysed day row carries ``envelope_id`` + ``envelope_version`` — also in
the single-envelope case. The top-level ``envelope_id``/``envelope_status``
fields and the informational notice remain keyed on the **latest** envelope
for backward compatibility; the per-day rows and
``envelope_versions_used`` are authoritative for history. Dates without approval
coverage are excluded from comparisons and listed under ``unattributed_days``.
"""

from __future__ import annotations

from datetime import date as date_type, timedelta
from functools import lru_cache
from typing import Any, Iterable, Literal, Optional

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
    dish_id: Optional[str] = None
    items: Optional[list[Serving]] = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def one_representation(self):
        if bool(self.dish_id) == bool(self.items):
            raise ValueError("Provide either dish_id or items")
        return self


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
    """Inclusive ISO window ending on the server's local date, not UTC.

    Logged dates are date-only values; this helper performs no timezone conversion.
    """
    end = date_type.today()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _envelope_notice(envelope: Any) -> tuple[bool, Optional[str]]:
    """Compatibility flag/notice for latest-envelope status, not day attribution."""
    status = envelope.status.value
    if status == "APPROVED":
        return False, None
    return True, (
        f"Envelope status is {status}; comparisons below are informational "
        "only — this envelope has not been approved by a clinician and must "
        "not be treated as clinical guidance."
    )


# ---------------------------------------------------------------------------
# Envelope-version attribution (Milestone 3)
# ---------------------------------------------------------------------------
def _resolve_day_envelopes(
    patient_id: str, dates: Iterable[str]
) -> tuple[dict[str, Optional[NutrientEnvelope]], list[str]]:
    """Map each logged date to the envelope effective on that date.

    Only approvals effective on or before consumption qualify. Missing coverage
    is reported explicitly; current targets cannot be applied retroactively.
    """
    assignment: dict[str, Optional[NutrientEnvelope]] = {}
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
    """Group logged days by their effective envelope and analyse per group.

    Returns ``{"groups": [...], "unattributed_days": [...], "latest": env}``
    where each group is ``{"envelope", "label", "dates", "logs", "result"}``.
    ``result`` is ``analyse_range`` output (``with_series=False``) or
    ``analyse_patient`` output (``with_series=True``). Groups are ordered
    chronologically by first covered date. ``label`` is the series-key prefix
    for multi-group responses: ``"<envelope_id>"``, or
    ``"<envelope_id>::v<version>"`` when one window spans multiple versions of
    the same envelope id (uniform for all groups in that response).
    """
    assignment, unattributed = _resolve_day_envelopes(
        patient_id, (log["date"] for log in logs)
    )
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for day in sorted(assignment):
        envelope = assignment[day]
        if envelope is None:
            continue
        key = (envelope.envelope_id, int(envelope.version))
        group = groups.setdefault(
            key, {"envelope": envelope, "dates": [], "logs": []}
        )
        group["dates"].append(day)
    for log in logs:
        envelope = assignment.get(log["date"])
        if envelope is None:
            continue
        groups[(envelope.envelope_id, int(envelope.version))]["logs"].append(log)

    ordered = sorted(
        groups.values(),
        key=lambda g: (g["dates"][0], g["envelope"].envelope_id, int(g["envelope"].version)),
    )
    # Series-key prefix: plain envelope id, disambiguated with the version when
    # one window spans multiple versions of the same envelope id.
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
    """``envelope_versions_used`` rows for an ``attributed_analysis`` result."""
    return [
        {
            "envelope_id": group["envelope"].envelope_id,
            "version": int(group["envelope"].version),
            "status": group["envelope"].status.value,
            "days": list(group["dates"]),
        }
        for group in attributed["groups"]
    ]


def _merged_aggregate(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stats recomputed across per-group day rows (multi-group only).

    Mirrors ``analysis.analyse_range``'s aggregate exactly, but over day rows
    that were classified against different envelope versions.
    """
    hard_by_nutrient: dict[str, int] = {}
    soft_by_nutrient: dict[str, int] = {}
    exposure_sum: dict[str, float] = {}
    exposure_days: dict[str, int] = {}
    for day in days:
        for row in day["hard_violations"]:
            nutrient = row.get("nutrient")
            if nutrient is None:
                continue  # dish-scoped exclusion violations
            hard_by_nutrient[nutrient] = hard_by_nutrient.get(nutrient, 0) + 1
        for row in day["soft_gaps"]:
            if not day["completeness"]["complete"]:
                continue
            soft_by_nutrient[row["nutrient"]] = soft_by_nutrient.get(row["nutrient"], 0) + 1
        for row in day["nutrients"]:
            if not day["completeness"]["complete"]:
                continue
            exposure_sum[row["nutrient"]] = exposure_sum.get(row["nutrient"], 0.0) + row["pct_deviation"]
            exposure_days[row["nutrient"]] = exposure_days.get(row["nutrient"], 0) + 1
    complete_days = sum(1 for day in days if day["completeness"]["complete"])
    return {
        "days_logged": len(days),
        "hard_violation_days": sum(1 for d in days if not d["compliant"]),
        "hard_violations_by_nutrient": dict(sorted(hard_by_nutrient.items())),
        "soft_gaps_by_nutrient": dict(sorted(soft_by_nutrient.items())),
        "mean_pct_deviation_by_nutrient": {
            nutrient: round(exposure_sum[nutrient] / exposure_days[nutrient], 4)
            for nutrient in sorted(exposure_sum)
        },
        "complete_days": complete_days,
        "fraction_complete": round(complete_days / len(days), 4) if days else 0.0,
    }


def _flag_sort_key(flag: dict[str, Any]) -> tuple[int, float]:
    order = {"worsening": 0, "improving": 1}
    return (order.get(flag["direction"], 2), -abs(flag["slope_pct_per_day"]))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/log", status_code=201, summary="Log an actual meal")
def log_meal(req: MealLogRequest) -> dict[str, Any]:
    _require_patient(req.patient_id)
    dish_ids = [item.dish_id for item in req.items] if req.items else [req.dish_id]
    missing = next((did for did in dish_ids if did not in _dish_index()), None)
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": missing},
        )
    try:
        date_type.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_date", "date": req.date},
        )
    return store.put_log(req.patient_id, date_type.fromisoformat(req.date).isoformat(), req.meal, dish_ids[0],
                         items=[item.model_dump() for item in req.items] if req.items else None)


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
    attributed = attributed_analysis(patient_id, logs, _dish_index(), with_series=False)
    groups = attributed["groups"]

    if len(groups) <= 1:
        # Legacy single-envelope shape (also covers the no-logs window).
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

    # Multi-envelope window: day rows keep their per-group classification
    # (each already stamped with envelope_id/envelope_version by analyse_day);
    # the aggregate is recomputed across the merged rows.
    merged_days = sorted(
        (day for group in groups for day in group["result"]["days"]),
        key=lambda day: day["date"],
    )
    aggregate = _merged_aggregate(merged_days)
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
    _require_patient(patient_id)
    envelope = _latest_envelope_or_404(patient_id)
    informational_only, notice = _envelope_notice(envelope)

    start, end = _date_window(days)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    attributed = attributed_analysis(patient_id, logs, _dish_index(), with_series=True)
    groups = attributed["groups"]

    if len(groups) <= 1:
        # Legacy single-envelope shape: plain series keys, plain flags.
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

    # Multi-envelope window: series keys are prefixed with the group's
    # envelope identity ("..." see attributed_analysis), flags merge across
    # groups with an envelope_id/envelope_version stamp each.
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
