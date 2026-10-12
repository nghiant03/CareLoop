"""Expose knowledge-base statistics."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.kb_loader import get_index, get_kb

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/stats", summary="Versioned knowledge-base statistics")
def kb_stats() -> dict:
    """Return database path, current version, and retrieval chunk count.

    Include current node counts by label and active edge counts by relation type.
    """
    kb = get_kb()
    stats = kb.stats()
    stats["retrieval_chunks"] = len(get_index().chunks)
    return stats
