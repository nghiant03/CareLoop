"""Clinician review queue — the closed adherence loop (Milestone 3).

``GET /review/queue`` derives review items **live** from three sources and
persists them idempotently:

* ``adherence_flag``    — worsening deviation trend flags from the patient's
  envelope-attributed deviation analysis (same 14-day window logic as
  ``GET /adherence/{id}/deviation``). One item per flag, keyed
  ``"<envelope-label>::<series_key>@<latest_point_date>"``.
* ``hard_violation_day`` — logged days with ``compliant=false``. Keyed
  ``"day@<date>"``.
* ``lab_trend``         — rising potassium / phosphate trends from
  :func:`backend.mining.trends.detect_trends` over the fixture patient record
  (skipped silently for patients without a lab series). Keyed
  ``"lab@<patient_id>:<analyte>"``.

**Deterministic identity.** Every derived condition maps to a stable review id
— the first 12 hex chars of ``sha1("{patient_id}|{source}|{key}")`` — so
repeated derivations (and process restarts) map to the *same* row instead of
duplicating it. On first sight the item is created via
``persistence.create_review_item``; afterwards the persisted row (its status in
particular) is authoritative.

**One-shot acknowledgement semantics.** Status flows ``OPEN → ACKNOWLEDGED →
ACTION_RECORDED`` ("actioned"). Because the id is a pure function of the
condition, an actioned item can never reappear as open even when the
underlying condition persists — acknowledging/recording an action once retires
that condition's queue entry for good. Re-derivation simply finds the existing
row and reports its stored status.

The clinician closes the loop on an item with ``POST /review/{id}/action``
(free-text action + note) or ``POST /review/{id}/proposal`` — the latter runs
the same rule-engine service as ``POST /rules/run`` (no HTTP hop), links the
freshly minted PROPOSED envelope to the item, and records a
``proposal_created`` action. The clinician then edits/approves the proposal
through the existing envelope endpoints.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.adherence import store
from backend.app.api.adherence import (
    _date_window,
    _dish_index,
    attributed_analysis,
)
from backend.app.api.patients import get_patient, list_patient_ids
from backend.app.api.rules import run_rules_service
from backend.app.core import persistence
from backend.mining.trends import detect_trends

router = APIRouter(prefix="/review", tags=["review"])

# Deviation window for the adherence-derived sources (mirrors the deviation
# endpoint's default).
_QUEUE_WINDOW_DAYS = 14

_STATUS_ALIASES = {
    "open": "OPEN",
    "acknowledged": "ACKNOWLEDGED",
    "actioned": "ACTION_RECORDED",
    "OPEN": "OPEN",
    "ACKNOWLEDGED": "ACKNOWLEDGED",
    "ACTION_RECORDED": "ACTION_RECORDED",
}


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    note: Optional[str] = None


def _map_status(raw: str) -> str:
    mapped = _STATUS_ALIASES.get(raw)
    if mapped is None:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_status", "status": raw},
        )
    return mapped


def _review_id(patient_id: str, source: str, key: str) -> str:
    """Stable 12-hex-char review id for one derived condition."""
    digest = hashlib.sha1(f"{patient_id}|{source}|{key}".encode("utf-8"))
    return digest.hexdigest()[:12]


def _compose_item(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten a persisted review row into the public item shape.

    The queue-created rows store ``{key, kind, severity, reason, payload}`` in
    ``payload_json``; rows created directly through the persistence layer (no
    queue metadata) fall back to exposing the stored payload verbatim.
    """
    stored = row["payload"] if isinstance(row["payload"], dict) else {}
    detail = stored.get("payload", stored)
    return {
        "review_id": row["review_id"],
        "patient_id": row["patient_id"],
        "source": row["source"],
        "key": stored.get("key"),
        "kind": stored.get("kind"),
        "severity": stored.get("severity"),
        "reason": stored.get("reason"),
        "status": row["status"],
        "created_at": row["created_at"],
        "acknowledged_at": row["acknowledged_at"],
        "payload": detail,
        "action": row["action"],
        "linked_envelope_id": row["linked_envelope_id"],
    }


def _upsert_derived(
    patient_id: str,
    source: str,
    key: str,
    kind: str,
    severity: str,
    reason: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Derive-to-row: create on first sight, then always read stored state.

    The stored row is authoritative (its status in particular), so a persisted
    ACKNOWLEDGED/ACTION_RECORDED item keeps its status even when the underlying
    condition still derives — one-shot acknowledgement semantics.
    """
    review_id = _review_id(patient_id, source, key)
    persistence.create_review_item(
        patient_id,
        source,
        {
            "key": key,
            "kind": kind,
            "severity": severity,
            "reason": reason,
            "payload": payload,
        },
        review_id=review_id,
    )
    row = persistence.get_review_item(review_id)
    assert row is not None  # just created (or pre-existing)
    return _compose_item(row)


def _latest_contributors(
    group: dict[str, Any], nutrient: str, kind: str
) -> list[dict[str, Any]]:
    """Contributors for one nutrient constraint from the group's latest day."""
    for day in reversed(group["result"]["days"]):
        if not day["completeness"]["complete"]:
            continue
        for row in day["nutrients"]:
            if row["nutrient"] == nutrient and row["kind"] == kind:
                return row.get("contributors", [])
    return []


def _derive_for_patient(patient_id: str) -> list[dict[str, Any]]:
    """All derivable review items for one patient (created idempotently)."""
    items: list[dict[str, Any]] = []

    start, end = _date_window(_QUEUE_WINDOW_DAYS)
    logs = store.list_logs(patient_id, date_from=start, date_to=end)
    attributed = attributed_analysis(
        patient_id, logs, _dish_index(), with_series=True
    )

    # 1. Worsening deviation trend flags (improving flags are good news and
    #    never enqueue; "alert" severity only ever co-occurs with worsening).
    for group in attributed["groups"]:
        envelope = group["envelope"]
        for flag in group["result"]["flags"]:
            if flag["direction"] != "worsening":
                continue
            series = group["result"]["series"][flag["series_key"]]
            latest_point_date = [p for p in series["points"] if p.get("complete", True)][-1]["date"]
            key = f"{group['label']}::{flag['series_key']}@{latest_point_date}"
            payload = dict(flag)
            payload["contributors"] = _latest_contributors(
                group, flag["nutrient"], flag["kind"]
            )
            items.append(
                _upsert_derived(
                    patient_id,
                    "adherence_flag",
                    key,
                    kind=f"{flag['nutrient']} {flag['direction']}",
                    severity=flag["severity"],
                    reason=flag["reason"],
                    payload=payload,
                )
            )

    # 2. Hard-violation days (hard ceilings exceeded or excluded dishes logged).
    for group in attributed["groups"]:
        for day in group["result"]["days"]:
            if day["compliant"]:
                continue
            parts: list[str] = []
            kind = "ceiling"
            for violation in day["hard_violations"]:
                if violation.get("type") == "excluded_dish":
                    kind = "excluded_dish"
                    parts.append(
                        f"{violation.get('dish_name')} is excluded "
                        f"({violation.get('exclusion_value')})"
                    )
                else:
                    parts.append(
                        f"{violation.get('nutrient')} over its "
                        f"{violation.get('kind')} ceiling"
                    )
            items.append(
                _upsert_derived(
                    patient_id,
                    "hard_violation_day",
                    f"day@{day['date']}",
                    kind=kind,
                    severity="alert",
                    reason=(
                        f"Hard violations on {day['date']}: " + "; ".join(parts)
                    ),
                    payload=day,
                )
            )

    # 3. Lab trends use durable dated observations when present, otherwise fixture
    #    monthly series. Sparse urgent observations can still warrant review.
    record = get_patient(patient_id)
    if record is not None:
        for trend in detect_trends([dict(record)]):
            if trend.get("patient_id") != patient_id:
                continue
            items.append(
                _upsert_derived(
                    patient_id,
                    "lab_trend",
                    f"lab@{patient_id}:{trend['analyte']}" + (f":{trend['observation_id']}" if trend.get('observation_id') else ""),
                    kind=trend["analyte"],
                    severity="alert" if trend["severity"] == "urgent" else "review",
                    reason=trend["reason"],
                    payload=dict(trend),
                )
            )

    return items


@router.get("/queue", summary="Derive + list the clinician review queue")
def review_queue(
    patient_id: Optional[str] = Query(default=None),
    status: str = Query(default="open"),
) -> dict[str, Any]:
    """Live-derived, idempotently-persisted review items.

    ``status`` filters the *persisted* status (default ``open``); derivation
    always runs so first-sight conditions are captured even when filtering for
    a later lifecycle stage.
    """
    mapped_status = None if status == "all" else _map_status(status)
    patient_ids = [patient_id] if patient_id else list_patient_ids()
    items: list[dict[str, Any]] = []
    for pid in patient_ids:
        items.extend(_derive_for_patient(pid))
    items = [_compose_item(row) for row in persistence.list_review_items(status=mapped_status, patient_id=patient_id)]
    items.sort(key=lambda item: (item["created_at"], item["review_id"]))
    return {"count": len(items), "items": items}


@router.get("/items", summary="Persisted review items (history / audit)")
def review_items(
    patient_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    mapped_status = _map_status(status) if status is not None else None
    rows = persistence.list_review_items(status=mapped_status, patient_id=patient_id)
    items = [_compose_item(row) for row in rows]
    return {"count": len(items), "items": items}


@router.post("/{review_id}/acknowledge", summary="Acknowledge a review item")
def acknowledge_review(review_id: str) -> dict[str, Any]:
    row = persistence.get_review_item(review_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "review_item_not_found", "review_id": review_id},
        )
    if row["status"] == "OPEN":
        row = persistence.acknowledge_review_item(review_id)
    # Idempotent: re-acknowledging (or acknowledging a later-stage item)
    # returns the item unchanged rather than regressing its status.
    return _compose_item(row)


@router.post("/{review_id}/action", summary="Record a clinician action")
def action_review(review_id: str, body: ActionRequest) -> dict[str, Any]:
    if persistence.get_review_item(review_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "review_item_not_found", "review_id": review_id},
        )
    updated = persistence.record_review_action(review_id, body.action, note=body.note)
    assert updated is not None
    return _compose_item(updated)


@router.post("/{review_id}/proposal", summary="Create a revised envelope proposal")
def proposal_review(review_id: str) -> dict[str, Any]:
    row = persistence.get_review_item(review_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "review_item_not_found", "review_id": review_id},
        )
    patient = get_patient(row["patient_id"])
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "patient_not_found",
                "patient_id": row["patient_id"],
            },
        )
    # Same code path as POST /rules/run (no HTTP hop): engine -> PROPOSED
    # envelope and embedded trace persisted together.
    result = run_rules_service(dict(patient))
    envelope = result["envelope"]
    updated = persistence.record_review_action(
        review_id,
        "proposal_created",
        note=None,
        linked_envelope_id=envelope.envelope_id,
    )
    assert updated is not None
    return {
        "review_item": _compose_item(updated),
        "envelope_id": envelope.envelope_id,
    }
