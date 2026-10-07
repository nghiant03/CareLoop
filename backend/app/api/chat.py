"""RAG chat endpoint (Week 1 stub).

Week 2 wires retrieval over the versioned knowledge base plus citation-required
prompting and an escalation filter. For now the endpoint returns a fixed stub
that already advertises the citation-required contract.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    patient_id: Optional[str] = None
    envelope_id: Optional[str] = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citation_required: bool = True
    citations: list[str] = []
    escalate: bool = False
    backend: str = "stub"


@router.post("", summary="Ask the (stub) RAG chatbot")
def chat(req: ChatRequest) -> ChatResponse:
    return ChatResponse(
        answer=(
            "RAG pipeline coming Week 2. Answers will be grounded in the "
            "versioned knowledge base and the patient's APPROVED envelope, "
            "with mandatory citations."
        ),
        citation_required=True,
        citations=[],
        escalate=False,
        backend="stub",
    )
