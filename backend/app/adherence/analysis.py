"""Deviation analysis: logged meals vs a nutrient envelope.

Hard/soft semantics (exactly as documented in ``backend/optim/problem.py`` and
``backend/optim/real_data.py`` — PLAN.md module 4):

* ``ConstraintKind.MAX``   : a **hard ceiling**. ``total > value`` is a hard
  violation (the optimiser never violates a MAX; here logged reality can).
* ``ConstraintKind.MIN``   : a **soft floor**. ``total < value`` is a soft aim
  gap — it steers guidance but never counts as a violation.
* ``ConstraintKind.TARGET``: a **soft desired value**. Any deviation
  (under *or* over) is a soft aim gap, reported with a signed direction.

Trend detection mirrors ``backend/mining/trends.py``: a Theil-Sen slope
(median of pairwise slopes — robust to outlier days) over the daily
deviation-exposure series, flagged as ``worsening`` / ``improving`` /
``stable``. All functions are pure and deterministic: inputs are sorted, no
randomness, no clocks.
"""

from __future__ import annotations

from datetime import date as date_type
from statistics import median
from typing import Any, Iterable, Mapping

from backend.optim.problem import exclusion_for
from backend.optim.toy_data import NUTRIENT_KEYS
from shared.envelope_schema import ConstraintKind, NutrientEnvelope, NutrientKind

from backend.app.adherence.store import MEALS

# Violation/gap magnitudes at or below this count as satisfied (float noise
# guard; mirrors problem.EPS / real_data._EPS).
EPS = 1e-9

# Trend flagging (deviation-exposure percentage points per day).
_MIN_SERIES_LEN = 3
_SLOPE_TRIGGER = 1.0          # |slope| above this is a directional trend
_ALERT_EXPOSURE_PCT = 25.0    # latest or 3-day projection >= this -> "alert"

_UNITS: dict[str, str] = {
    kind.value: unit
    for kind, unit in {
        NutrientKind.ENERGY_KCAL: "kcal",
        NutrientKind.PROTEIN_G: "g",
        NutrientKind.SODIUM_MG: "mg",
        NutrientKind.POTASSIUM_MG: "mg",
        NutrientKind.PHOSPHORUS_MG: "mg",
        NutrientKind.CARBS_G: "g",
        NutrientKind.FAT_G: "g",
        NutrientKind.SAT_FAT_G: "g",
        NutrientKind.FIBER_G: "g",
        NutrientKind.SUGAR_G: "g",
    }.items()
}


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def day_totals(
    dish_ids: Iterable[str],
    dish_by_id: Mapping[str, Any],
) -> dict[str, float]:
    """Sum per-serving nutrients over the dishes logged for one day.

    Unknown dish ids are skipped by contract (the API layer 404s them before
    anything is stored, so a miss here means external tampering, not user
    input). Zero totals for an empty day.
    """
    totals = {key: 0.0 for key in NUTRIENT_KEYS}
    for dish_id in dish_ids:
        dish = dish_by_id.get(dish_id)
        if dish is None:
            continue
        for key in NUTRIENT_KEYS:
            totals[key] += dish.nutrient(key)
    return totals


# ---------------------------------------------------------------------------
# Per-constraint classification
# ---------------------------------------------------------------------------
def _pct(numerator: float, limit: float) -> float:
    """Percentage of the limit, guarded against a zero/absurd limit."""
    denom = limit if limit > EPS else 1e-9
    return numerator / denom * 100.0


def classify_constraint(nutrient: str, kind: ConstraintKind, limit: float, total: float) -> dict[str, Any]:
    """Classify one day's total for one envelope constraint.

    Returns a row::

        {"nutrient", "kind", "unit", "limit", "total", "deviation",
         "pct_deviation", "direction", "status"}

    ``status`` is ``"hard_violation"`` (MAX exceeded), ``"soft_gap"`` (MIN
    shortfall or TARGET off-value) or ``"ok"``. ``deviation`` is signed
    (total - limit); ``pct_deviation`` is the *exposure* magnitude (>= 0, in
    the "bad" direction only) used for trends.
    """
    unit = _UNITS.get(nutrient, "")
    row: dict[str, Any] = {
        "nutrient": nutrient,
        "kind": kind.value,
        "unit": unit,
        "limit": round(limit, 6),
        "total": round(total, 6),
        "deviation": round(total - limit, 6),
        "direction": None,
        "status": "ok",
        "pct_deviation": 0.0,
    }
    if kind is ConstraintKind.MAX:
        if total - limit > EPS:
            row["status"] = "hard_violation"
            row["direction"] = "over"
            row["pct_deviation"] = round(_pct(total - limit, limit), 4)
    elif kind is ConstraintKind.MIN:
        if limit - total > EPS:
            row["status"] = "soft_gap"
            row["direction"] = "under"
            row["pct_deviation"] = round(_pct(limit - total, limit), 4)
    else:  # TARGET — soft desired value; either side is an aim gap
        if abs(total - limit) > EPS:
            row["status"] = "soft_gap"
            row["direction"] = "over" if total > limit else "under"
            row["pct_deviation"] = round(abs(_pct(total - limit, limit)), 4)
    return row


def analyse_day(
    date: str,
    entries: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
    dish_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    """Per-day totals + hard/soft classification for one logged day.

    ``entries`` are meal-log dicts for the day (any meal order). Dishes are
    summed across all logged meals of the day.

    Hard exclusions from the envelope are enforced per logged dish: a dish
    hit by any exclusion flag is a hard violation for that day (mirroring the
    optimiser's treatment of exclusions as hard constraints), independent of
    whether its nutrients happen to stay under the ceilings.
    """
    meal_order = {m: i for i, m in enumerate(MEALS)}
    ordered = sorted(entries, key=lambda e: meal_order.get(e.get("meal", ""), 99))
    totals = day_totals((e["dish_id"] for e in ordered), dish_by_id)

    rows = [
        classify_constraint(c.nutrient.value, c.kind, float(c.value), totals[c.nutrient.value])
        for c in sorted(envelope.targets, key=lambda c: (c.nutrient.value, c.kind.value))
    ]
    hard = [r for r in rows if r["status"] == "hard_violation"]
    for entry in ordered:
        dish = dish_by_id.get(entry.get("dish_id"))
        if dish is None:
            continue
        flag = exclusion_for(dish, envelope)
        if flag is None:
            continue
        hard.append(
            {
                "type": "excluded_dish",
                "dish_id": entry.get("dish_id"),
                "dish_name": getattr(dish, "name", None),
                "meal": entry.get("meal"),
                "exclusion_kind": flag.kind.value,
                "exclusion_value": flag.value,
                "reason": flag.reason,
            }
        )
    soft = [r for r in rows if r["status"] == "soft_gap"]
    return {
        "date": date,
        "meals": [
            {"meal": e.get("meal"), "dish_id": e.get("dish_id")} for e in ordered
        ],
        "totals": {k: round(v, 6) for k, v in totals.items()},
        "nutrients": rows,
        "hard_violations": hard,
        "soft_gaps": soft,
        "compliant": not hard,
    }


# ---------------------------------------------------------------------------
# Range analysis
# ---------------------------------------------------------------------------
def analyse_range(
    logs: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
    dish_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    """Per-day analyses + aggregate stats over a chronological log list.

    Days with no logs are simply absent (a fasted day says nothing about what
    was eaten). Deterministic: days sorted ascending, rows sorted per day.
    """
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for entry in logs:
        by_date.setdefault(entry["date"], []).append(entry)

    days = [
        analyse_day(date, entries, envelope, dish_by_id)
        for date, entries in sorted(by_date.items())
    ]

    hard_by_nutrient: dict[str, int] = {}
    soft_by_nutrient: dict[str, int] = {}
    exposure_sum: dict[str, float] = {}
    exposure_days: dict[str, int] = {}
    for day in days:
        for row in day["hard_violations"]:
            nutrient = row.get("nutrient")
            if nutrient is None:
                # Exclusion violations are dish-scoped (no nutrient axis);
                # they still count towards ``hard_violation_days`` below.
                continue
            hard_by_nutrient[nutrient] = hard_by_nutrient.get(nutrient, 0) + 1
        for row in day["soft_gaps"]:
            soft_by_nutrient[row["nutrient"]] = soft_by_nutrient.get(row["nutrient"], 0) + 1
        for row in day["nutrients"]:
            exposure_sum[row["nutrient"]] = exposure_sum.get(row["nutrient"], 0.0) + row["pct_deviation"]
            exposure_days[row["nutrient"]] = exposure_days.get(row["nutrient"], 0) + 1

    mean_exposure = {
        nutrient: round(exposure_sum[nutrient] / exposure_days[nutrient], 4)
        for nutrient in sorted(exposure_sum)
    }
    aggregate = {
        "days_logged": len(days),
        "hard_violation_days": sum(1 for d in days if not d["compliant"]),
        "hard_violations_by_nutrient": dict(sorted(hard_by_nutrient.items())),
        "soft_gaps_by_nutrient": dict(sorted(soft_by_nutrient.items())),
        "mean_pct_deviation_by_nutrient": mean_exposure,
    }
    return {"days": days, "aggregate": aggregate}


# ---------------------------------------------------------------------------
# Time series + trend flags
# ---------------------------------------------------------------------------
def _theil_sen_slope(times: list[float], values: list[float]) -> float:
    """Median of all pairwise slopes (classic Theil-Sen, as mining/trends.py)
    computed against *elapsed days* rather than observation indices, so
    unevenly spaced observations yield a true per-day rate. Pairs with zero
    elapsed time (duplicate dates) cannot define a per-day rate and are
    skipped."""
    n = len(values)
    slopes = [
        (values[j] - values[i]) / (times[j] - times[i])
        for i in range(n - 1)
        for j in range(i + 1, n)
        if times[j] - times[i] > 0
    ]
    return float(median(slopes)) if slopes else 0.0


def _day_offsets(dates: list[Any]) -> list[float]:
    """Elapsed-day axis for series points: ordinal day numbers for ISO dates,
    falling back to the list position for anything unparsable."""
    offsets: list[float] = []
    for i, raw in enumerate(dates):
        try:
            offsets.append(float(date_type.fromisoformat(str(raw)).toordinal()))
        except (TypeError, ValueError):
            offsets.append(float(i))
    return offsets


def deviation_series(
    day_analyses: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
) -> dict[str, dict[str, Any]]:
    """Per-constraint daily deviation time-series (chronological).

    Each point carries the signed ``pct`` (total vs limit, signed) and the
    ``exposure`` magnitude in the bad direction (>= 0) used for trending:

    * ``MAX``    — excess over the ceiling;
    * ``MIN``    — shortfall below the floor (exposure *grows* as intake
      falls further under the limit);
    * ``TARGET`` — absolute distance from the desired value.

    A nutrient constrained on both sides (e.g. protein MIN + MAX) gets one
    series per constraint so each limit and direction is applied correctly
    with exactly one point per date per series: single-constraint nutrients
    keep the plain nutrient key, multi-constraint nutrients are keyed
    ``"<nutrient>:<kind>"``.
    """
    constraints = sorted(envelope.targets, key=lambda c: (c.nutrient.value, c.kind.value))
    constraint_count: dict[str, int] = {}
    for constraint in constraints:
        nutrient_key = constraint.nutrient.value
        constraint_count[nutrient_key] = constraint_count.get(nutrient_key, 0) + 1

    per_nutrient: dict[str, dict[str, Any]] = {}
    days = sorted(day_analyses, key=lambda d: d["date"])
    for constraint in constraints:
        nutrient = constraint.nutrient.value
        key = (
            nutrient
            if constraint_count[nutrient] == 1
            else f"{nutrient}:{constraint.kind.value}"
        )
        series = per_nutrient.setdefault(
            key,
            {
                "nutrient": nutrient,
                "kind": constraint.kind.value,
                "unit": _UNITS.get(nutrient, ""),
                "limit": float(constraint.value),
                "points": [],
            },
        )
        points = series["points"]
        for day in days:
            total = day["totals"].get(nutrient, 0.0)
            signed = _pct(total - series["limit"], series["limit"])
            if constraint.kind is ConstraintKind.MAX:
                exposure = max(0.0, signed)
            elif constraint.kind is ConstraintKind.MIN:
                exposure = max(0.0, -signed)
            else:  # TARGET — either side of the desired value is exposure
                exposure = abs(signed)
            points.append(
                {
                    "date": day["date"],
                    "total": round(total, 6),
                    "pct": round(signed, 4),
                    "exposure": round(exposure, 4),
                }
            )
    return dict(sorted(per_nutrient.items()))


def trend_flags(
    series: Mapping[str, Mapping[str, Any]],
    min_len: int = _MIN_SERIES_LEN,
    slope_trigger: float = _SLOPE_TRIGGER,
) -> list[dict[str, Any]]:
    """Flag directional deviation trends from the exposure series.

    A flag is emitted when the Theil-Sen slope of the exposure series against
    the observation *dates* (per elapsed day, not per observation index)
    exceeds ``slope_trigger`` (worsening) or falls below ``-slope_trigger``
    (improving). Sorted worst-first (worsening before improving, larger
    |slope| first). Deterministic.
    """
    flags: list[dict[str, Any]] = []
    for nutrient in sorted(series):
        s = series[nutrient]
        points = s["points"]
        exposures = [p["exposure"] for p in points]
        if len(exposures) < min_len:
            continue
        slope = _theil_sen_slope(_day_offsets([p["date"] for p in points]), exposures)
        if abs(slope) <= slope_trigger:
            continue
        direction = "worsening" if slope > 0 else "improving"
        latest = exposures[-1]
        projected = max(0.0, latest + 3.0 * slope)
        alert = direction == "worsening" and (
            latest >= _ALERT_EXPOSURE_PCT or projected >= _ALERT_EXPOSURE_PCT
        )
        flags.append(
            {
                "nutrient": nutrient,
                "kind": s["kind"],
                "slope_pct_per_day": round(slope, 4),
                "direction": direction,
                "severity": "alert" if alert else "review",
                "latest_exposure_pct": round(latest, 4),
                "projected_3d_exposure_pct": round(projected, 4),
                "reason": (
                    f"{nutrient} deviation {direction} at {slope:+.2f} pct-points/day "
                    f"(latest {latest:.1f}%, 3-day projection {projected:.1f}%)"
                ),
            }
        )
    order = {"worsening": 0, "improving": 1}
    flags.sort(key=lambda f: (order[f["direction"]], -abs(f["slope_pct_per_day"])))
    return flags


def analyse_patient(
    logs: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
    dish_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    """One-shot helper: range analysis + series + trend flags."""
    result = analyse_range(logs, envelope, dish_by_id)
    series = deviation_series(result["days"], envelope)
    return {
        "days": result["days"],
        "aggregate": result["aggregate"],
        "series": series,
        "flags": trend_flags(series),
    }


__all__ = [
    "EPS",
    "day_totals",
    "classify_constraint",
    "analyse_day",
    "analyse_range",
    "deviation_series",
    "trend_flags",
    "analyse_patient",
]