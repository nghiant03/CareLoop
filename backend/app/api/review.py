"""Derive and persist clinician review items from adherence and lab observations.

``GET /review/queue`` writes newly seen conditions even when filtering for a
later status. IDs are stable hashes of patient, source, and condition key;
re-derivation preserves the first stored payload and current status.

Adherence uses a 14-day historically attributed window. Lab trends prefer dated
observations over fixture series; dated alerts include the latest observation
ID in their key, allowing a new observation to create a distinct review item.

Acknowledgement, actions, and proposal links update stored review state.
Acknowledgement advances only OPEN items in storage, so a concurrently
recorded action cannot be regressed. Proposals use the shared rule service
and still require separate clinician approval before live planning.

Proposal creation and review linkage commit separately. A failed linkage
write leaves a recoverable partial success: a pending action records the exact
envelope ID atomically with its snapshot. A retry re-links that proposal,
including scope-rejected results, rather than minting another.
Finalization only consumes the matching pending identity. A superseded
completion returns 409 without replacing a newer proposal or clinician action.
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


def _ensure_derived_review_item(
    patient_id: str,
    source: str,
    key: str,
    kind: str,
    severity: str,
    reason: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create on first sight; repeated derivation preserves stored payload and status."""
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

    # Improving trends do not require review; enqueue only worsening flags.
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
                _ensure_derived_review_item(
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
                _ensure_derived_review_item(
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
                _ensure_derived_review_item(
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
    """Advance an OPEN item to ACKNOWLEDGED; later statuses are preserved.

    The transition is conditional in storage, so an action recorded
    concurrently wins; the response returns the item's current status.
    """
    updated = persistence.acknowledge_review_item(review_id)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "review_item_not_found", "review_id": review_id},
        )
    return _compose_item(updated)


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
    """Create and link a fresh proposal, recovering a partial earlier attempt.

    A failure between proposal persistence and the linkage write leaves the
    proposal unlinked. Its snapshot and exact pending identity commit together,
    so a retry re-links it without selecting an unrelated same-patient proposal.
    A superseded completion returns 409; newer review state is left intact.
    """
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
    action = row["action"] or {}
    envelope_id = action.get("envelope_id") if action.get("action") == "proposal_pending" else None
    if envelope_id is None:
        with persistence.begin_review_proposal(review_id):
            result = run_rules_service(dict(patient))
        envelope_id = result["envelope"].envelope_id
    try:
        updated = persistence.finalize_review_proposal(review_id, envelope_id)
    except persistence.ReviewProposalConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "review_proposal_superseded", "review_id": review_id,
                    "envelope_id": envelope_id},
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "review_item_not_found", "review_id": review_id},
        )
    return {
        "review_item": _compose_item(updated),
        "envelope_id": envelope_id,
    }
