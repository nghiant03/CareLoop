"""Envelope lifecycle endpoints: approve / edit / reject.

Only ``POST /envelopes/{envelope_id}/approve`` moves an envelope into the
APPROVED state that satisfies the downstream approval gate. ``edit`` moves it to
EDITED (awaiting re-confirmation) and ``reject`` to REJECTED — both remain
blocked downstream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.core.approval_gate import get_envelope_or_404, put_envelope
from backend.app.core.trace_store import get_trace, put_trace, trace_or_none
from backend.app.explain.views import clinician_explanation
from backend.app.models.envelope import (
    CitationSource,
    EnvelopeStatus,
    ExclusionFlag,
    NutrientConstraint,
    NutrientEnvelope,
    RuleFire,
)

router = APIRouter(prefix="/envelopes", tags=["envelopes"])


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``approved_by``/``notes`` are the original fields; ``clinician_id``/``note``
    # are the frontend-contract aliases (either form is accepted).
    approved_by: str = "clinician"
    notes: Optional[str] = None
    clinician_id: Optional[str] = None
    note: Optional[str] = None

    @property
    def approver(self) -> str:
        return self.clinician_id or self.approved_by

    @property
    def approval_note(self) -> Optional[str]:
        return self.note if self.note is not None else self.notes


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: Optional[list[NutrientConstraint]] = None
    exclusions: Optional[list[ExclusionFlag]] = None
    notes: Optional[str] = None
    edited_by: str = "clinician"


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str = "clinician"
    reason: Optional[str] = None


@router.get("/latest", summary="Latest envelope for a patient")
def read_latest_envelope_for_patient(
    patient_id: str = Query(..., description="Patient id"),
) -> NutrientEnvelope:
    """The patient's most recent envelope, any status.

    Lets the what-if screen prefill its target editor from the current
    envelope (the proposal baseline) instead of retyping every constraint.
    """
    from backend.app.core.approval_gate import find_latest_envelope_for_patient

    envelope = find_latest_envelope_for_patient(patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": patient_id},
        )
    return envelope


@router.get("/{envelope_id}", summary="Get an envelope")
def read_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    return envelope


@router.get("/{envelope_id}/explanation", summary="Clinician explanation of an envelope")
def explain_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> dict:
    """Structured clinician view: fired rules, conflict resolutions, cited
    constraints. Falls back to the envelope's embedded ``fired_rules`` when no
    separate trace was pinned."""
    trace = trace_or_none(envelope) or []
    return clinician_explanation(envelope.model_dump(by_alias=True), trace)


def _out_of_scope(envelope: NutrientEnvelope) -> bool:
    """True when the envelope must never be approved into the downstream gate.

    Out-of-scope proposals (pregnancy, dialysis, ketoacidosis risk, ...) are
    REJECTED with empty targets and a ``careloop_eligible=false`` note. The
    approval gate hard-blocks them: approving such an envelope would hand the
    optimiser a constraint set with nothing to violate.
    """
    if envelope.status == EnvelopeStatus.REJECTED:
        return True
    if not envelope.targets:
        return True
    return "careloop_eligible=false" in (envelope.notes or "")


@router.post("/{envelope_id}/approve", summary="Approve an envelope")
def approve_envelope(
    body: ApproveRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or ApproveRequest()
    if _out_of_scope(envelope):
        # Documented error body: {"error": "out_of_scope_envelope", ...}
        return JSONResponse(
            status_code=422,
            content={
                "error": "out_of_scope_envelope",
                "envelope_id": envelope.envelope_id,
                "status": envelope.status.value,
            },
        )
    envelope.status = EnvelopeStatus.APPROVED
    envelope.approved_by = body.approver
    envelope.approved_at = datetime.now(timezone.utc)
    if body.approval_note is not None:
        envelope.notes = body.approval_note
    return put_envelope(envelope)


def _clinician_edit_row(envelope: NutrientEnvelope, body: EditRequest) -> RuleFire:
    """Trace row recording a clinician-authored edit.

    An edit replaces targets that were produced by fired rules, so the original
    rule citations no longer back the new numbers. The explicit CLINICIAN-EDIT
    row keeps the trace honest and stops chat from attaching an unrelated
    guideline citation to a clinician-authored value.
    """
    if body.targets is not None:
        set_pieces = "; ".join(
            f"set {t.nutrient.value} {t.kind.value} = {t.value:g} {t.unit}"
            for t in body.targets
        )
        action = f"clinician override: targets replaced ({set_pieces or 'no constraints'})"
    else:
        action = "clinician override: targets unchanged"
    if body.exclusions is not None:
        action += f"; exclusions replaced ({len(body.exclusions)} entries)"
    return RuleFire(
        rule_id="CLINICIAN-EDIT",
        fired_at=datetime.now(timezone.utc),
        patient_summary=f"clinician edit by {body.edited_by}",
        action_summary=action,
        priority=0,
        citation=CitationSource(
            guideline="clinician override",
            section="clinician edit",
            rule_id="CLINICIAN-EDIT",
        ),
    )


@router.post("/{envelope_id}/edit", summary="Edit an envelope (awaiting re-approval)")
def edit_envelope(
    body: EditRequest,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    if body.targets is not None:
        envelope.targets = body.targets
    if body.exclusions is not None:
        envelope.exclusions = body.exclusions
    if body.notes is not None:
        envelope.notes = body.notes
    # An edit invalidates any prior approval: clinician must re-confirm.
    envelope.status = EnvelopeStatus.EDITED
    envelope.approved_by = None
    envelope.approved_at = None
    envelope.version += 1

    # Append the clinician-edit marker to the pinned trace and the embedded
    # fired_rules so explanations and chat see that the numbers are no longer
    # rule-produced.
    edit_row = _clinician_edit_row(envelope, body)
    stored = get_trace(envelope.envelope_id)
    if stored is None:
        stored = trace_or_none(envelope) or []
    put_trace(envelope.envelope_id, list(stored) + [edit_row.model_dump(mode="json", by_alias=True)])
    envelope.fired_rules = list(envelope.fired_rules) + [edit_row]
    if body.targets is not None:
        from shared.provenance import attach_provenance

        attach_provenance(envelope, author=body.edited_by, citation=edit_row.citation)

    return put_envelope(envelope)


@router.post("/{envelope_id}/reject", summary="Reject an envelope")
def reject_envelope(
    body: RejectRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or RejectRequest()
    envelope.status = EnvelopeStatus.REJECTED
    envelope.approved_by = None
    envelope.approved_at = None
    if body.reason:
        envelope.notes = body.reason
    return put_envelope(envelope)
