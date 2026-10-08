"""Process-local meal-log store (Week 1 prototype).

Mirrors the :mod:`backend.app.core.approval_gate` ``ENVELOPE_STORE`` pattern: a
dict keyed by a natural identifier, guarded by a lock, with storage-agnostic
module-level functions so Week 2+ can swap in a persistent table without
touching callers.

Log entry shape (plain dict)::

    {
        "patient_id": "P0001",
        "date": "2026-10-08",            # ISO calendar day (local care day)
        "meal": "breakfast",             # breakfast | lunch | dinner
        "dish_id": "SG0001",
        "logged_at": "2026-10-08T02:14:09.123456+00:00",
    }

**Upsert semantics per (patient_id, date, meal)**: a patient logs one dish per
meal slot; logging the same slot again replaces the previous dish (the newest
log wins) rather than accumulating rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Optional

MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner")

# Keyed by (patient_id, date, meal) -> entry dict.
MEAL_LOGS: dict[tuple[str, str, str], dict[str, str]] = {}
_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(patient_id: str, date: str, meal: str) -> tuple[str, str, str]:
    return (patient_id, date, meal)


def put_log(
    patient_id: str,
    date: str,
    meal: str,
    dish_id: str,
    logged_at: Optional[str] = None,
) -> dict[str, str]:
    """Insert or replace the log for one (patient, date, meal) slot."""
    entry = {
        "patient_id": patient_id,
        "date": date,
        "meal": meal,
        "dish_id": dish_id,
        "logged_at": logged_at or _now_iso(),
    }
    with _LOCK:
        MEAL_LOGS[_key(patient_id, date, meal)] = entry
    return dict(entry)


def get_log(patient_id: str, date: str, meal: str) -> Optional[dict[str, str]]:
    """Return the log for one slot, or ``None``."""
    with _LOCK:
        entry = MEAL_LOGS.get(_key(patient_id, date, meal))
    return dict(entry) if entry is not None else None


def list_logs(
    patient_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, str]]:
    """All logs for a patient, chronological (date, then meal order).

    ``date_from`` / ``date_to`` are inclusive ISO date bounds.
    """
    with _LOCK:
        entries = [e for e in MEAL_LOGS.values() if e["patient_id"] == patient_id]
    meal_order = {m: i for i, m in enumerate(MEALS)}
    out = []
    for entry in entries:
        if date_from is not None and entry["date"] < date_from:
            continue
        if date_to is not None and entry["date"] > date_to:
            continue
        out.append(dict(entry))
    out.sort(key=lambda e: (e["date"], meal_order.get(e["meal"], 99)))
    return out


def delete_logs_for_patient(patient_id: str) -> int:
    """Remove every log for a patient; returns the number deleted."""
    with _LOCK:
        stale = [k for k, e in MEAL_LOGS.items() if e["patient_id"] == patient_id]
        for k in stale:
            del MEAL_LOGS[k]
    return len(stale)


def count_logs(patient_id: Optional[str] = None) -> int:
    """Number of stored logs (optionally for one patient)."""
    with _LOCK:
        if patient_id is None:
            return len(MEAL_LOGS)
        return sum(1 for e in MEAL_LOGS.values() if e["patient_id"] == patient_id)


def clear() -> None:
    """Empty the store (test/prototype helper)."""
    with _LOCK:
        MEAL_LOGS.clear()


__all__ = [
    "MEALS",
    "MEAL_LOGS",
    "put_log",
    "get_log",
    "list_logs",
    "delete_logs_for_patient",
    "count_logs",
    "clear",
]