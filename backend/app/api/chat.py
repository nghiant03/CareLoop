"""Expose grounded nutrition chat with patient and envelope identity checks."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.patients import get_patient
from backend.app.chat import answers
from backend.app.core.approval_gate import (
    find_latest_envelope_for_patient,
    get_envelope,
)
from backend.app.core.kb_loader import get_kb

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Nutrition question to answer.")
    patient_id: str | None = Field(
        default=None,
        description="Patient context. Omit both IDs for anonymous guideline chat.",
    )
    envelope_id: str | None = Field(
        default=None,
        description="Explicit envelope to use instead of the patient's latest proposal.",
    )


class ChatCitation(BaseModel):
    rule_id: str | None
    guideline: str | None
    url: str | None = Field(
        description="Source URL, or null for clinician-authored provenance.",
    )


class ChatResponse(BaseModel):
    answer: str
    claims: list[dict[str, Any]]
    citations: list[ChatCitation]
    escalated: bool = Field(description="True only when status is escalated.")
    status: Literal["answered", "refused", "escalated"]


def _citation_brief(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": citation.get("rule_id"),
        "guideline": citation.get("guideline"),
        "url": citation.get("url"),
    }


@router.post(
    "",
    summary="Ask the grounded RAG chatbot",
    responses={
        200: {"model": ChatResponse, "description": "Answered, refused, or escalated chat."},
        404: {"description": "An explicitly requested patient or envelope was not found."},
        409: {"description": "The requested patient differs from the envelope's patient."},
    },
)
def chat(req: ChatRequest) -> dict[str, Any]:
    """Resolve one patient's context for grounded nutrition chat.

    Prefer an explicit envelope over the patient's latest proposal. Use the
    envelope's own patient for applicability and body weight. A missing profile
    may fall back to the frozen snapshot only when the patient ID was inferred
    from the envelope, not explicitly requested.

    Reject unknown explicit IDs and mismatched identities. Envelopes may have
    any lifecycle status, but only approved values become personal target guidance.
    See ``docs/ARCHITECTURE.md`` for grounding, citation, refusal, and escalation.
    """
    patient_id = req.patient_id
    envelope_obj = None
    if req.envelope_id is not None:
        envelope_obj = get_envelope(req.envelope_id)
        if envelope_obj is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "envelope_not_found", "envelope_id": req.envelope_id},
            )
        if patient_id is not None and patient_id != envelope_obj.patient_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "patient_envelope_mismatch",
                    "patient_id": patient_id,
                    "envelope_id": req.envelope_id,
                },
            )
        patient_id = envelope_obj.patient_id
    elif patient_id is not None:
        envelope_obj = find_latest_envelope_for_patient(patient_id)

    envelope = envelope_obj.model_dump(by_alias=True, mode="json") if envelope_obj else None

    patient = get_patient(patient_id) if patient_id is not None else None
    if patient is None and req.patient_id is not None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": req.patient_id},
        )

    result = answers.answer(
        req.message, get_kb(), envelope=envelope, role="patient", patient=patient
    )

    return {
        "answer": result["answer"],
        "claims": result.get("claims", []),
        "citations": [_citation_brief(c) for c in result["citations"]],
        "escalated": result["status"] == "escalated",
        "status": result["status"],
    }
