"""Trace side-store for explainability.

The approval gate (``core/approval_gate.py``) keeps its storage-agnostic
envelope contract untouched; this module adds a process-local side table that
pins the rule-engine trace (the ``RuleFire`` list) alongside each envelope id
so ``GET /envelopes/{id}/explanation`` can reconstruct the decision exactly as
it was proposed. Week 2+ swaps both stores for a persistent backing table
without changing either contract.
"""

from __future__ import annotations

from typing import Any, Optional
from threading import Lock

__all__ = ["TRACE_STORE", "put_trace", "get_trace", "trace_or_none"]

TRACE_STORE: dict[str, list[dict[str, Any]]] = {}
_LOCK = Lock()


def put_trace(envelope_id: str, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Store (or replace) the trace for an envelope id."""
    with _LOCK:
        TRACE_STORE[envelope_id] = list(trace or [])
    return TRACE_STORE[envelope_id]


def get_trace(envelope_id: str) -> Optional[list[dict[str, Any]]]:
    with _LOCK:
        trace = TRACE_STORE.get(envelope_id)
    return list(trace) if trace is not None else None


def trace_or_none(envelope: Any) -> Optional[list[dict[str, Any]]]:
    """Trace for an envelope, falling back to its embedded ``fired_rules``."""
    envelope_id = getattr(envelope, "envelope_id", None) or (
        envelope.get("envelope_id") if isinstance(envelope, dict) else None
    )
    if envelope_id is not None:
        stored = get_trace(str(envelope_id))
        if stored is not None:
            return stored
    fired = getattr(envelope, "fired_rules", None)
    if fired is None and isinstance(envelope, dict):
        fired = envelope.get("fired_rules")
    if fired:
        return [
            row.model_dump(by_alias=True) if hasattr(row, "model_dump") else row
            for row in fired
        ]
    return None