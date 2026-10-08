"""Meal-log store — SQLite-backed (Milestone 3).

Historically a process-local dict (Week 1 prototype). Since Milestone 3 the
logs live in the shared application database
(:mod:`backend.app.core.persistence`, table ``meal_logs``), so they survive a
process restart and are visible to every worker. The public function
names/signatures are unchanged — callers (``backend.app.api.adherence``,
analysis tests) do not need to know about the storage swap.

Log entry shape (plain dict)::

    {
        "patient_id": "P0001",
        "date": "2026-10-08",            # ISO calendar day (local care day)
        "meal": "breakfast",             # breakfast | lunch | dinner
        "dish_id": "SG0001",
        "items": [{"dish_id": "SG0001", "quantity": 0.5}],
        "logged_at": "2026-10-08T02:14:09.123456+00:00",
    }

**Upsert semantics per (patient_id, date, meal)**: saving a slot replaces its
entire item list. ``items`` carries dish IDs and serving quantities; legacy
entries without it represent one serving of ``dish_id``.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.app.core import persistence

MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner")


def put_log(
    patient_id: str,
    date: str,
    meal: str,
    dish_id: str,
    logged_at: Optional[str] = None,
    items: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Insert or replace the log for one (patient, date, meal) slot."""
    return persistence.put_log(patient_id, date, meal, dish_id, logged_at, items=items)


def get_log(patient_id: str, date: str, meal: str) -> Optional[dict[str, Any]]:
    """Return the log for one slot, or ``None``."""
    return persistence.get_log(patient_id, date, meal)


def list_logs(
    patient_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    """All logs for a patient, chronological (date, then meal order).

    ``date_from`` / ``date_to`` are inclusive ISO date bounds.
    """
    return persistence.list_logs(patient_id, date_from=date_from, date_to=date_to)


def delete_logs_for_patient(patient_id: str) -> int:
    """Remove every log for a patient; returns the number deleted."""
    return persistence.delete_logs_for_patient(patient_id)


def count_logs(patient_id: Optional[str] = None) -> int:
    """Number of stored logs (optionally for one patient)."""
    return persistence.count_logs(patient_id)


def clear() -> None:
    """Delete every meal log (test/prototype helper)."""
    persistence.clear_logs()


__all__ = [
    "MEALS",
    "put_log",
    "get_log",
    "list_logs",
    "delete_logs_for_patient",
    "count_logs",
    "clear",
]
