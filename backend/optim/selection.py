from __future__ import annotations

from .problem import (
    ConstraintKind,
    daily_totals,
    scalar_score,
)
from .toy_data import Dish

_UNMET_TOL = 1e-9


def _flat_ids(entry: dict) -> tuple[str, ...]:
    return tuple(d for meal in entry["plan"] for d in meal)


def _relative(num: float, aim: float) -> float:
    if aim > 0:
        return num / aim
    return float(num)


def _relative_day_deviation(totals: dict[str, float], envelope) -> float:
    constraints = list(envelope.targets)
    if not constraints:
        return 0.0
    total = 0.0
    for c in constraints:
        aim = float(c.value)
        value = totals[c.nutrient.value]
        if c.kind == ConstraintKind.TARGET:
            total += _relative(abs(value - aim), aim)
        elif c.kind == ConstraintKind.MIN:
            total += _relative(max(0.0, aim - value), aim)
        else:
            total += _relative(max(0.0, value - aim), aim)
    return total / len(constraints)


def scalar_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    return min(entries, key=lambda e: (scalar_score(e["objectives"]), _flat_ids(e)))


def normalised_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Nonpositive aims use absolute gaps."""
    def key(entry: dict) -> tuple:
        daily = daily_totals(entry["plan"], dishes)
        if not daily:
            mean_rel = 0.0
        else:
            mean_rel = sum(_relative_day_deviation(t, envelope) for t in daily) / len(daily)
        return (mean_rel, _flat_ids(entry))

    return min(entries, key=key)


def adequacy_first_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Rank worst relative aim deviation before unmet aim count and scalar score."""
    def key(entry: dict) -> tuple:
        daily = daily_totals(entry["plan"], dishes)
        worst = 0.0
        unmet = 0
        for totals in daily:
            for c in envelope.targets:
                if c.kind == ConstraintKind.MAX:
                    continue
                aim = float(c.value)
                value = totals[c.nutrient.value]
                if c.kind == ConstraintKind.MIN:
                    shortfall = max(0.0, aim - value)
                else:
                    shortfall = abs(value - aim)
                rel = _relative(shortfall, aim)
                worst = max(worst, rel)
                if rel > _UNMET_TOL:
                    unmet += 1
        return (worst, unmet, scalar_score(entry["objectives"]), _flat_ids(entry))

    return min(entries, key=key)


__all__ = [
    "adequacy_first_selection",
    "normalised_selection",
    "scalar_selection",
]
