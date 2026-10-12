"""Deterministic selection of a headline plan from feasible front entries.

Supply a nonempty list of feasible entries with ``plan`` and ``objectives``,
plus the original approved envelope, not a solver-relaxed copy. These functions
do not validate approval or feasibility. Empty entry lists raise ValueError.
The selected entry is returned by identity; mutating it also changes the
supplied front.

Strategies
----------
* :func:`scalar_selection` — scalar baseline: minimise
  ``problem.scalar_score`` of the entry's objective vector (placeholder
  weights, raw nutrient units), with a dish-ID tie-break.
* :func:`normalised_selection` — minimise the mean over days of the
  per-nutrient RELATIVE deviation vs the original envelope aims
  (``|total - aim| / aim`` for TARGET, ``shortfall / aim`` for MIN,
  ``excess / aim`` for MAX), so kcal / mg / g units stop dominating the
  raw-unit mixing in ``problem.SCALAR_WEIGHTS``.
* :func:`adequacy_first_selection` — lexicographic:
  1. minimise the largest relative deviation over all day/aim pairs: MIN
     shortfall or absolute TARGET distance. Exclude hard MAX ceilings;
  2. minimise the count of unmet day-aim pairs (relative shortfall > 1e-9);
  3. minimise ``scalar_score``.

All strategies break score ties on the plan's flattened dish-ID tuple. Relative
deviations fall back to absolute gaps when an aim is nonpositive. Inputs are
unchanged; entries with identical keys retain input order.
"""

from __future__ import annotations

from .problem import (
    ConstraintKind,
    daily_totals,
    scalar_score,
)
from .toy_data import Dish

_UNMET_TOL = 1e-9


def _flat_ids(entry: dict) -> tuple[str, ...]:
    """Deterministic tie-break key: the plan's flattened dish-id tuple."""
    return tuple(d for meal in entry["plan"] for d in meal)


def _relative(num: float, aim: float) -> float:
    """``num / aim`` with an absolute fallback when ``aim <= 0``."""
    if aim > 0:
        return num / aim
    return float(num)


def _relative_day_deviation(totals: dict[str, float], envelope) -> float:
    """Mean over constraints of the relative deviation for one day."""
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
        else:  # MAX
            total += _relative(max(0.0, value - aim), aim)
    return total / len(constraints)


def scalar_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Minimise scalar_score, breaking ties by flattened dish IDs."""
    return min(entries, key=lambda e: (scalar_score(e["objectives"]), _flat_ids(e)))


def normalised_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Minimise mean relative deviation over days and envelope constraints.

    Use TARGET distance, MIN shortfall, and MAX excess. Nonpositive aims use
    absolute gaps. See the module contract for input requirements and tie-breaks.
    """
    def key(entry: dict) -> tuple:
        daily = daily_totals(entry["plan"], dishes)
        if not daily:
            mean_rel = 0.0
        else:
            mean_rel = sum(_relative_day_deviation(t, envelope) for t in daily) / len(daily)
        return (mean_rel, _flat_ids(entry))

    return min(entries, key=key)


def adequacy_first_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Lexicographic adequacy-first selection (see module docstring).

    Key: ``(worst relative aim deviation, unmet day-aim count,
    scalar_score, flattened dish IDs)``. MIN uses shortfall. TARGET uses
    two-sided distance. See ``_relative`` for nonpositive aims.
    """
    def key(entry: dict) -> tuple:
        daily = daily_totals(entry["plan"], dishes)
        worst = 0.0
        unmet = 0
        for totals in daily:
            for c in envelope.targets:
                if c.kind == ConstraintKind.MAX:
                    continue  # ceilings are hard constraints, not adequacy aims
                aim = float(c.value)
                value = totals[c.nutrient.value]
                if c.kind == ConstraintKind.MIN:
                    shortfall = max(0.0, aim - value)
                else:  # TARGET: absolute deviation includes overshoot
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
