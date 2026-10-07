"""Knowledge-base observability endpoint.

``GET /kb/stats`` — node/edge counts, current version tag and retrieval-index
size of the process knowledge base (useful for demos and /healthz-adjacent
debugging).
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.kb_loader import get_index, get_kb

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/stats", summary="Versioned knowledge-base statistics")
def kb_stats() -> dict:
    kb = get_kb()
    stats = kb.stats()
    stats["retrieval_chunks"] = len(get_index().chunks)
    return stats