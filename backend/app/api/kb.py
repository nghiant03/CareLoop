"""Expose knowledge-base statistics."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.kb_loader import get_index, get_kb
from backend.knowledge.runtime import selected_release, source_hashes

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/stats", summary="Versioned knowledge-base statistics")
def kb_stats() -> dict:
    """Return database path, current version, and retrieval chunk count.

    Include current node counts by label and active edge counts by relation type.
    """
    kb = get_kb()
    stats = kb.stats()
    stats["retrieval_chunks"] = len(get_index().chunks)
    release = selected_release()
    stats["knowledge_release_id"] = release.release_id if release else None
    stats["knowledge_source_hashes"] = source_hashes()
    return stats
