"""Authorize planning from durable approved envelopes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Lock

from fastapi import Depends, HTTPException, Path
from pydantic import BaseModel

from backend.app.models.envelope import NutrientEnvelope

logger = logging.getLogger("careloop.approval_gate")

__all__ = [
    "ENVELOPE_STORE",
    "EnvelopeNotApprovedError",
    "PlanRequest",
    "assert_approved",
    "find_latest_envelope_for_patient",
    "get_envelope",
    "get_envelope_or_404",
    "list_envelopes",
    "put_envelope",
    "require_approved_envelope",
    "require_approved_envelope_for_patient",
]


class EnvelopeNotApprovedError(Exception):
    def __init__(self, envelope: NutrientEnvelope) -> None:
        self.envelope = envelope
        self.status = envelope.status.value
        super().__init__(
            f"envelope {envelope.envelope_id!r} is {self.status}, not APPROVED"
        )


# Compatibility mirror only. Live reads use PostgreSQL.

ENVELOPE_STORE: dict[str, NutrientEnvelope] = {}
_STORE_LOCK = Lock()


def put_envelope(envelope: NutrientEnvelope, *, new_proposal: bool = False) -> NutrientEnvelope:
    """Persist before publishing the cache. The supplied object may be mutated."""
    from backend.app.core import persistence

    with _STORE_LOCK:
        persistence.store_envelope(envelope, new_proposal=new_proposal)
        ENVELOPE_STORE[envelope.envelope_id] = envelope
    return envelope


def get_envelope(envelope_id: str) -> NutrientEnvelope | None:
    return next((env for env in list_envelopes() if env.envelope_id == envelope_id), None)


def list_envelopes() -> list[NutrientEnvelope]:
    from backend.app.core import persistence

    return persistence.current_envelopes()


def find_latest_envelope_for_patient(patient_id: str) -> NutrientEnvelope | None:
    """Order by proposal time. A newer pending proposal takes precedence over an approval."""
    candidates = [env for env in list_envelopes() if env.patient_id == patient_id]
    if not candidates:
        return None
    return max(candidates, key=lambda env: env.proposed_at)


def assert_approved(envelope: NutrientEnvelope) -> NutrientEnvelope:
    if not envelope.is_ready_for_optimisation():
        raise EnvelopeNotApprovedError(envelope)
    return envelope


def get_envelope_or_404(
    envelope_id: str = Path(..., description="Envelope id"),
) -> NutrientEnvelope:
    envelope = get_envelope(envelope_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="envelope_not_found")
    return envelope


def require_approved_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    return assert_approved(envelope)


class PlanRequest(BaseModel):
    patient_id: str


def require_approved_envelope_for_patient(
    req: PlanRequest,
) -> NutrientEnvelope:
    """A newer pending proposal blocks planning despite an older approval."""
    envelope = find_latest_envelope_for_patient(req.patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "envelope_not_found",
                "patient_id": req.patient_id,
            },
        )
    return assert_approved(envelope)


def utcnow() -> datetime:
    return datetime.now(UTC)
