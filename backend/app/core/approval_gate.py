"""Approval-gate invariant.

Live planning requires an APPROVED, scope-eligible envelope with nonempty targets.
HTTP dependencies enforce this gate. Informational views and chat may inspect
other lifecycle states; personal target guidance still requires approval.
See docs/ARCHITECTURE.md for the lifecycle and chat contracts.

Use ``require_approved_envelope`` for path-keyed requests and
``require_approved_envelope_for_patient`` for a ``PlanRequest`` body.

Failure of any gate condition raises :class:`EnvelopeNotApprovedError`, which
``backend.app.main`` renders as HTTP 409 with body::

    {"error": "envelope_not_approved", "status": "<CURRENT_STATUS>"}

The SQLite journal is authoritative for live reads and atomic proposal IDs.
"""

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
    """Raised when approval, scope eligibility, or nonempty targets are missing."""

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
    """Persist and cache the supplied envelope, returning that same object.

    Mutations and stale-revision conflicts follow ``persistence.store_envelope``;
    ``new_proposal`` assigns a fresh identity and proposal time. Callers needing
    an unchanged input must copy it first. Cache publication follows the write.
    """
    from backend.app.core import persistence

    with _STORE_LOCK:
        persistence.store_envelope(envelope, new_proposal=new_proposal)
        ENVELOPE_STORE[envelope.envelope_id] = envelope
    return envelope


def get_envelope(envelope_id: str) -> NutrientEnvelope | None:
    """Return an envelope by id, or ``None``."""
    return next((env for env in list_envelopes() if env.envelope_id == envelope_id), None)


def list_envelopes() -> list[NutrientEnvelope]:
    """Return fresh durable snapshots ordered by their latest journal row.

    Updating an existing identity moves it later in this order.
    """
    from backend.app.core import persistence

    return persistence.current_envelopes()


def find_latest_envelope_for_patient(patient_id: str) -> NutrientEnvelope | None:
    """Return the most recently proposed envelope for a patient, if any.

    Order by ``proposed_at``, not content version or approval time. On equal
    proposal timestamps, retain the first candidate in latest-journal-row order.
    A newer unapproved proposal takes precedence over an older approval.
    """
    candidates = [env for env in list_envelopes() if env.patient_id == patient_id]
    if not candidates:
        return None
    return max(candidates, key=lambda env: env.proposed_at)


def assert_approved(envelope: NutrientEnvelope) -> NutrientEnvelope:
    """Return the input if APPROVED, scope-eligible, and carrying nutrient targets.

    Raise :class:`EnvelopeNotApprovedError` if any condition fails.
    """
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
    """Dependency: require planning readiness of the patient's latest proposal.

    ``req`` is parsed from the request body by FastAPI; the endpoint declares the
    same model. A newer pending proposal blocks planning even if an older
    envelope was approved.
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
    return datetime.now(UTC)
