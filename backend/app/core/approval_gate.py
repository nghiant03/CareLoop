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

Week 1 uses a process-local in-memory store. Week 2+ will swap the store for a
persistent backing table without changing the gate contract.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, Path
from pydantic import BaseModel

from backend.app.models.envelope import EnvelopeStatus, NutrientEnvelope

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
# In-memory envelope store (Week 1)
# ---------------------------------------------------------------------------

ENVELOPE_STORE: dict[str, NutrientEnvelope] = {}
_STORE_LOCK = Lock()


_ENVELOPE_ID_SEQ = re.compile(r"^(?P<base>.+)-(?P<seq>\d{3})$")


def put_envelope(envelope: NutrientEnvelope) -> NutrientEnvelope:
    """Insert or replace an envelope in the store.

    Re-running the rule engine re-mints the same first id (``ENV-<pid>-001``).
    When a *freshly built* envelope object arrives for an id that already
    exists, that is a new proposal for the patient — not a lifecycle update —
    so the store mints the next sequential id (``ENV-<pid>-002``, ...) and
    stamps the real wall-clock ``proposed_at``. This keeps prior envelopes,
    including APPROVED ones and their approval history, intact.

    Lifecycle updates (approve / edit / reject) re-store the very same object
    that was loaded from the store; that case is detected by object identity
    and stored in place under the existing id.
    """
    with _STORE_LOCK:
        existing = ENVELOPE_STORE.get(envelope.envelope_id)
        if existing is not None and existing is not envelope:
            match = _ENVELOPE_ID_SEQ.match(envelope.envelope_id)
            base = match["base"] if match else envelope.envelope_id
            seq = int(match["seq"]) + 1 if match else 2
            while f"{base}-{seq:03d}" in ENVELOPE_STORE:
                seq += 1
            # Mutate in place (not model_copy): callers (e.g. POST /rules/run)
            # keep using the same object and must observe the minted id.
            envelope.envelope_id = f"{base}-{seq:03d}"
            envelope.proposed_at = utcnow()
        ENVELOPE_STORE[envelope.envelope_id] = envelope
    return envelope


def get_envelope(envelope_id: str) -> Optional[NutrientEnvelope]:
    """Return an envelope by id, or ``None``."""
    with _STORE_LOCK:
        return ENVELOPE_STORE.get(envelope_id)


def list_envelopes() -> list[NutrientEnvelope]:
    """Return all envelopes (insertion order)."""
    with _STORE_LOCK:
        return list(ENVELOPE_STORE.values())


def find_latest_envelope_for_patient(patient_id: str) -> Optional[NutrientEnvelope]:
    """Return the most recently proposed envelope for a patient, if any.

    Ordering is by ``proposed_at`` alone: each rule-engine run now mints a
    fresh sequential envelope id, so comparing ``version`` across different
    envelope ids is meaningless (every fresh proposal restarts at version 1).
    """
    with _STORE_LOCK:
        candidates = [
            env for env in ENVELOPE_STORE.values() if env.patient_id == patient_id
        ]
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
