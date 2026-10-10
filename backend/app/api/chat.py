"""RAG chat endpoint.

``POST /chat`` body ``{"patient_id": "...", "message": "...", "envelope_id":
"..."}`` — answers via the grounded pipeline (``backend.app.chat.answers.answer``)
over the process knowledge base. An explicit ``envelope_id`` takes precedence
over the patient's latest proposal, and applicability/body-weight context is
derived from the envelope's own patient. Either may have any status; only
approved values become personal target guidance.

Explicitly requested identities are resolved strictly: an unknown
``envelope_id`` or ``patient_id`` returns 404 (omitting both keeps anonymous
guideline chat), and a ``patient_id`` conflicting with the envelope's patient
returns 409 — one patient's envelope must never be answered with another
patient's profile context. Response contract:

``{"answer": str, "claims": [...], "citations": [{"rule_id", "guideline", "url"}],
  "escalated": bool, "status": "answered"|"refused"|"escalated"}``

Escalated out-of-scope requests get ``escalated: true`` with the safety
message; low-confidence questions are refused (``escalated: false``) with a
see-your-clinician text. Every answered response carries at least one source
citation: a guideline rule, or a ``CLINICIAN-EDIT`` provenance (without URL)
when the clinician authored the value — edited values never claim guideline
authorship.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.chat import answers
from backend.app.core.kb_loader import get_kb
from backend.app.api.patients import get_patient
from backend.app.core.approval_gate import (
    find_latest_envelope_for_patient,
    get_envelope,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    patient_id: Optional[str] = None
    envelope_id: Optional[str] = None


def _citation_brief(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": citation.get("rule_id"),
        "guideline": citation.get("guideline"),
        "url": citation.get("url"),
    }


@router.post("", summary="Ask the grounded RAG chatbot")
def chat(req: ChatRequest) -> dict[str, Any]:
    # Keep envelope values, applicability, and weight on one patient identity.
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

    # Only envelope-derived missing profiles may use the frozen snapshot.
    # Explicitly requested unknown patients are errors, not anonymous chat.
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
