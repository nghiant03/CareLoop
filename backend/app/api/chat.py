"""RAG chat endpoint.

``POST /chat`` body ``{"patient_id": "...", "message": "..."}`` — answers via
the grounded pipeline (``backend.app.chat.answers.answer``) over the process
knowledge base, passing the patient's latest envelope (any status) so numbers
and approval state can be reflected. Response contract:

``{"answer": str, "citations": [{"rule_id", "guideline", "url"}],
  "escalated": bool, "status": "answered"|"refused"|"escalated"}``

Escalated out-of-scope requests get ``escalated: true`` with the safety
message; low-confidence questions are refused (``escalated: false``) with a
see-your-clinician text. Every answered response carries at least one
guideline citation.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
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
    envelope_obj = None
    if req.envelope_id:
        envelope_obj = get_envelope(req.envelope_id)
    elif req.patient_id:
        envelope_obj = find_latest_envelope_for_patient(req.patient_id)

    envelope = envelope_obj.model_dump(by_alias=True, mode="json") if envelope_obj else None

    # The patient record lets per-kg rulebook coefficients (25-35 kcal/kg,
    # g/kg protein) be rendered as computed daily amounts instead of raw
    # coefficients that read like absolute daily doses.
    patient = get_patient(req.patient_id) if req.patient_id else None

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
