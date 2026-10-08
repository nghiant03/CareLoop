"""Trace serialization, with legacy side-store helpers for older callers.

Envelope snapshots carry the authoritative trace, including an explicitly empty
trace. Only inputs without a ``fired_rules`` field consult the legacy side store.
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
    """Read the snapshot's trace; never let a process cache override durable data."""
    fired = getattr(envelope, "fired_rules", None)
    if fired is None and isinstance(envelope, dict):
        fired = envelope.get("fired_rules")
    if fired is not None:
        return [
            row.model_dump(mode="json", by_alias=True) if hasattr(row, "model_dump") else row
            for row in fired
        ]
    envelope_id = getattr(envelope, "envelope_id", None) or (
        envelope.get("envelope_id") if isinstance(envelope, dict) else None
    )
    if envelope_id is not None:
        stored = get_trace(str(envelope_id))
        if stored is not None:
            return stored
    return None
