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
    return persistence.put_log(patient_id, date, meal, dish_id, logged_at, items=items)


def get_log(patient_id: str, date: str, meal: str) -> dict[str, Any] | None:
    return persistence.get_log(patient_id, date, meal)


def list_logs(
    patient_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    return persistence.list_logs(patient_id, date_from=date_from, date_to=date_to)


def delete_logs_for_patient(patient_id: str) -> int:
    return persistence.delete_logs_for_patient(patient_id)


def count_logs(patient_id: str | None = None) -> int:
    return persistence.count_logs(patient_id)


def clear() -> None:
    """Use only with an isolated database."""
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
