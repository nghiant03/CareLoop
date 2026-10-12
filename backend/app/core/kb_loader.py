"""Process-wide knowledge-base singleton for the API layer.

Loads ``rules/rules.json`` + ``data/dishes.json`` into the versioned
``KBGraph`` in in-memory SQLite and caches the retrieval index per built graph.
Called from the app lifespan for warm-up and lazily by the
chat / kb-stats endpoints, so tests and tools can import the module without
side effects.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.app.chat.retrieval import KBIndex, build_index
from backend.app.kb.graph_store import KBGraph, load_kb

logger = logging.getLogger("careloop.kb")

__all__ = ["get_index", "get_kb", "reset_kb"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "rules" / "rules.json"
DISHES_PATH = _REPO_ROOT / "data" / "dishes.json"

_KB: KBGraph | None = None


def get_kb() -> KBGraph:
    """Return the process KB, building it on first use."""
    global _KB
    if _KB is None:
        kb = load_kb(RULES_PATH, DISHES_PATH)  # in-memory SQLite
        _KB = kb
        logger.info(
            "knowledge base loaded: %s",
            {k: v for k, v in kb.stats()["node_counts"].items()},
        )
    return _KB


def get_index() -> KBIndex:
    """Retrieval index over the process KB (cached per KBGraph instance)."""
    return build_index(get_kb())


def reset_kb() -> None:
    """Clear and close the process KB; the next access loads source files again."""
    global _KB
    if _KB is not None:
        _KB.close()
    _KB = None
