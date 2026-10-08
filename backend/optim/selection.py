"""Front-selection strategies (Milestone 2).

A selection strategy picks ONE headline plan from the solver's feasible front
entries (dicts with ``"plan"``, ``"objectives"``, ``"feasible"``).  The
strategies here are scored against the ORIGINAL approved envelope passed in —
never a pool-relaxed or aim-adjusted ("solved") copy — so selection quality is
always measured against what the clinician actually approved.

Strategies
----------
* :func:`scalar_selection` — the current behaviour: minimise
  ``problem.scalar_score`` of the entry's objective vector (placeholder
  weights, raw nutrient units).  Re-exported here as the comparison baseline.
* :func:`normalised_selection` — minimise the mean over days of the
  per-nutrient RELATIVE deviation vs the original envelope aims
  (``|total - aim| / aim`` for TARGET, ``shortfall / aim`` for MIN,
  ``excess / aim`` for MAX), so kcal / mg / g units stop dominating the
  raw-unit mixing the system review flagged in ``problem.SCALAR_WEIGHTS``.
* :func:`adequacy_first_selection` — lexicographic:
  1. minimise the WORST-day worst-constraint relative shortfall across the
     MIN/TARGET aims (the max shortfall fraction over all day x aim pairs;
     TARGET aims count two-sided ``|total - aim| / aim`` as shortfall of the
     aim; MAX ceilings are hard constraints, not adequacy aims);
  2. minimise the count of unmet day-aim pairs (relative shortfall > 1e-9);
  3. minimise ``scalar_score``.

All three are pure and deterministic: the same entries always yield the same
pick, and ties on a strategy's key are broken on the plan's flattened dish-id
tuple (``scalar_selection`` adds this tie-break to the historical
``min(key=scalar_score)``, which only differs on exact score ties).
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
    """Current behaviour: minimise ``problem.scalar_score`` (baseline)."""
    return min(entries, key=lambda e: (scalar_score(e["objectives"]), _flat_ids(e)))


def normalised_selection(entries: list[dict], envelope, dishes: list[Dish]) -> dict:
    """Minimise the mean per-day per-nutrient RELATIVE deviation.

    Scores against the ORIGINAL approved envelope aims, normalised per
    constraint so kcal/mg/g scales no longer dominate raw-unit scalar scores.
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

    Key: ``(worst-day worst-constraint relative shortfall across MIN/TARGET
    aims, count of unmet day-aim pairs, scalar_score, dish-id tuple)``.
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
                else:  # TARGET: two-sided shortfall vs the aim
                    shortfall = abs(value - aim)
                rel = _relative(shortfall, aim)
                if rel > worst:
                    worst = rel
                if rel > _UNMET_TOL:
                    unmet += 1
        return (worst, unmet, scalar_score(entry["objectives"]), _flat_ids(entry))

    return min(entries, key=key)


__all__ = [
    "scalar_selection",
    "normalised_selection",
    "adequacy_first_selection",
]