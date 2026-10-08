"""Approval-gate invariant.

Hard architectural rule (PLAN.md §2.3): a nutrient envelope is ``PROPOSED``
until a clinician approves/edits/rejects it, and **only APPROVED envelopes may
be consumed downstream** (optimiser, RAG chat, patient-facing views). This is
enforced in the API layer, not by convention.

Usage in an endpoint that reads an envelope::

    from backend.app.core.approval_gate import require_approved_envelope

    @router.post("/plans")
    def create_plan(
        envelope: NutrientEnvelope = Depends(require_approved_envelope_for_patient),
    ):
        ...

Any non-approved status raises :class:`EnvelopeNotApprovedError`, which
``backend.app.main`` renders as HTTP 409 with body::

    {"error": "envelope_not_approved", "status": "<CURRENT_STATUS>"}

The SQLite journal is authoritative for live reads and atomic proposal IDs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, Path
from pydantic import BaseModel

from backend.app.models.envelope import EnvelopeStatus, NutrientEnvelope

logger = logging.getLogger("careloop.approval_gate")

__all__ = [
    "EnvelopeNotApprovedError",
    "ENVELOPE_STORE",
    "put_envelope",
    "get_envelope",
    "list_envelopes",
    "find_latest_envelope_for_patient",
    "assert_approved",
    "get_envelope_or_404",
    "require_approved_envelope",
    "PlanRequest",
    "require_approved_envelope_for_patient",
]


class EnvelopeNotApprovedError(Exception):
    """Raised when a non-APPROVED envelope reaches a downstream endpoint."""

    def __init__(self, envelope: NutrientEnvelope) -> None:
        self.envelope = envelope
        self.status = envelope.status.value
        super().__init__(
            f"envelope {envelope.envelope_id!r} is {self.status}, not APPROVED"
        )


# ---------------------------------------------------------------------------
# Compatibility mirror; live reads always use SQLite
# ---------------------------------------------------------------------------

ENVELOPE_STORE: dict[str, NutrientEnvelope] = {}
_STORE_LOCK = Lock()


def put_envelope(envelope: NutrientEnvelope, *, new_proposal: bool = False) -> NutrientEnvelope:
    """Persist a lifecycle update, or atomically mint a fresh proposal id."""
    from backend.app.core import persistence

    with _STORE_LOCK:
        persistence.store_envelope(envelope, new_proposal=new_proposal)
        ENVELOPE_STORE[envelope.envelope_id] = envelope
    return envelope


def get_envelope(envelope_id: str) -> Optional[NutrientEnvelope]:
    """Return an envelope by id, or ``None``."""
    return next((env for env in list_envelopes() if env.envelope_id == envelope_id), None)


def list_envelopes() -> list[NutrientEnvelope]:
    """Return all envelopes (insertion order)."""
    from backend.app.core import persistence

    return persistence.current_envelopes()


def find_latest_envelope_for_patient(patient_id: str) -> Optional[NutrientEnvelope]:
    """Return the most recently proposed envelope for a patient, if any.

    Ordering is by ``proposed_at`` alone: each rule-engine run now mints a
    fresh sequential envelope id, so comparing ``version`` across different
    envelope ids is meaningless (every fresh proposal restarts at version 1).
    """
    candidates = [env for env in list_envelopes() if env.patient_id == patient_id]
    if not candidates:
        return None
    return max(candidates, key=lambda env: env.proposed_at)


def assert_approved(envelope: NutrientEnvelope) -> NutrientEnvelope:
    """Raise :class:`EnvelopeNotApprovedError` unless the envelope is APPROVED."""
    if not envelope.is_ready_for_optimisation():
        raise EnvelopeNotApprovedError(envelope)
    return envelope


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_envelope_or_404(
    envelope_id: str = Path(..., description="Envelope id"),
) -> NutrientEnvelope:
    """Dependency: load an envelope by path id or raise 404."""
    envelope = get_envelope(envelope_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="envelope_not_found")
    return envelope


def require_approved_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    """Dependency: enforce the approval gate on an ``{envelope_id}`` path param."""
    return assert_approved(envelope)


class PlanRequest(BaseModel):
    """Body for ``POST /plans`` — identifies the patient to plan for."""

    patient_id: str


def require_approved_envelope_for_patient(
    req: PlanRequest,
) -> NutrientEnvelope:
    """Dependency: gate ``POST /plans`` on the patient's approved envelope.

    ``req`` is parsed from the request body by FastAPI; the endpoint declares the
    same model so the parsed body is shared (FastAPI caches body parsing).
    """
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
    """Timezone-aware UTC now (helper shared by endpoints)."""
    return datetime.now(timezone.utc)
