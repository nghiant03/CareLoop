"""Meal-log facade over the durable application store.

Slots are keyed by patient, ISO date, and meal. Writes replace the whole slot;
input validation belongs to the API. Persistence owns timestamps and ordering.
"""

from __future__ import annotations

from typing import Any

from backend.app.core import persistence

MEALS: tuple[str, ...] = ("breakfast", "lunch", "dinner")


def put_log(
    patient_id: str,
    date: str,
    meal: str,
    dish_id: str,
    logged_at: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replace a slot's complete dish/item list; see ``persistence.put_log``."""
    return persistence.put_log(patient_id, date, meal, dish_id, logged_at, items=items)


def get_log(patient_id: str, date: str, meal: str) -> dict[str, Any] | None:
    """Return the stored slot, or ``None`` if it has not been logged."""
    return persistence.get_log(patient_id, date, meal)


def list_logs(
    patient_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """List logs by date then meal order, with inclusive optional ISO date bounds."""
    return persistence.list_logs(patient_id, date_from=date_from, date_to=date_to)


def delete_logs_for_patient(patient_id: str) -> int:
    """Remove every log for a patient; returns the number deleted."""
    return persistence.delete_logs_for_patient(patient_id)


def count_logs(patient_id: Optional[str] = None) -> int:
    """Count logged meal slots, optionally for one patient, not individual dishes."""
    return persistence.count_logs(patient_id)


def clear() -> None:
    """Delete all patients' meal logs; intended for isolated tests."""
    persistence.clear_logs()


__all__ = [
    "MEALS",
    "clear",
    "count_logs",
    "delete_logs_for_patient",
    "get_log",
    "list_logs",
    "put_log",
]
