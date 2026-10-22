"""Score logged meals against the supplied envelope."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from statistics import median
from typing import Any

from backend.app.adherence.store import MEALS
from backend.optim.problem import exclusion_for
from backend.optim.toy_data import NUTRIENT_KEYS
from shared.envelope_schema import ConstraintKind, NutrientEnvelope, NutrientKind

EPS = 1e-9

_MIN_SERIES_LEN = 3
# Slope threshold uses percentage points per elapsed day.
_SLOPE_TRIGGER = 1.0
_ALERT_EXPOSURE_PCT = 25.0

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


def day_totals(
    dish_ids: Iterable[str],
    dish_by_id: Mapping[str, Any],
) -> dict[str, float]:
    """Unknown dishes are skipped. Quantities are not applied."""
    totals = {key: 0.0 for key in NUTRIENT_KEYS}
    for dish_id in dish_ids:
        dish = dish_by_id.get(dish_id)
        if dish is None:
            continue
        for key in NUTRIENT_KEYS:
            totals[key] += dish.nutrient(key)
    return totals


def _pct(numerator: float, limit: float) -> float:
    denom = limit if limit > EPS else 1e-9
    return numerator / denom * 100.0


def classify_constraint(nutrient: str, kind: ConstraintKind, limit: float, total: float) -> dict[str, Any]:
    """Only MAX excess is a hard violation. MIN and TARGET misses are soft gaps."""
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
    else:
        if abs(total - limit) > EPS:
            row["status"] = "soft_gap"
            row["direction"] = "over" if total > limit else "under"
            row["pct_deviation"] = round(abs(_pct(total - limit, limit)), 4)
    return row


def _completeness(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    meals_logged = len({e.get("meal") for e in entries if e.get("meal") in MEALS})
    return {
        "meals_logged": meals_logged,
        "expected_meals": len(MEALS),
        "complete": meals_logged >= len(MEALS),
    }


def _contributors(
    nutrient: str,
    highest_first: bool,
    entries: Iterable[Mapping[str, Any]],
    dish_by_id: Mapping[str, Any],
    day_total: float,
) -> list[dict[str, Any]]:
    """Rank logged entries without merging repeated dish IDs."""
    per_dish: list[tuple[str, Any, float]] = []
    for entry in entries:
        dish = dish_by_id.get(entry.get("dish_id", ""))
        if dish is None:
            continue
        per_dish.append(
            (str(dish.dish_id), getattr(dish, "name", None), float(dish.nutrient(nutrient)) * entry.get("quantity", 1))
        )
    per_dish.sort(key=lambda t: ((-t[2] if highest_first else t[2]), t[0]))
    out: list[dict[str, Any]] = []
    for dish_id, dish_name, amount in per_dish[:2]:
        pct = amount / day_total * 100.0 if day_total > EPS else 0.0
        out.append(
            {
                "dish_id": dish_id,
                "dish_name": dish_name,
                "amount": round(amount, 6),
                "pct_of_day_total": round(pct, 4),
            }
        )
    return out


def analyse_day(
    date: str,
    entries: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
    dish_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    """Callers select historical approval coverage. Unknown dishes still count toward meal completeness."""
    meal_order = {m: i for i, m in enumerate(MEALS)}
    ordered = sorted(entries, key=lambda e: meal_order.get(e.get("meal", ""), 99))
    ordered = [dict(item, meal=entry.get("meal"))
               for entry in ordered for item in entry.get("items", [entry])]
    totals = {key: sum(dish_by_id[e["dish_id"]].nutrient(key) * e.get("quantity", 1)
                       for e in ordered if e["dish_id"] in dish_by_id)
              for key in NUTRIENT_KEYS}

    rows = [
        classify_constraint(c.nutrient.value, c.kind, float(c.value), totals[c.nutrient.value])
        for c in sorted(envelope.targets, key=lambda c: (c.nutrient.value, c.kind.value))
    ]
    for row in rows:
        row["contributors"] = _contributors(
            row["nutrient"],
            highest_first=row["kind"] == ConstraintKind.MAX.value,
            entries=ordered,
            dish_by_id=dish_by_id,
            day_total=totals[row["nutrient"]],
        )
    hard = [r for r in rows if r["status"] == "hard_violation"]
    for entry in ordered:
        dish = dish_by_id.get(entry.get("dish_id") or "")
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
            {"meal": e.get("meal"), "dish_id": e.get("dish_id"), "quantity": e.get("quantity", 1)} for e in ordered
        ],
        "totals": {k: round(v, 6) for k, v in totals.items()},
        "nutrients": rows,
        "hard_violations": hard,
        "soft_gaps": soft,
        "compliant": not hard,
        "completeness": _completeness(ordered),
        "envelope_id": envelope.envelope_id,
        "envelope_version": envelope.version,
    }


def analyse_range(
    logs: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
    dish_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    """Callers must split logs by effective envelope version."""
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for entry in logs:
        by_date.setdefault(entry["date"], []).append(entry)

    days = [
        analyse_day(date, entries, envelope, dish_by_id)
        for date, entries in sorted(by_date.items())
    ]

    return {"days": days, "aggregate": aggregate_days(days)}


def aggregate_days(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Count hard violations on all days. Only complete days contribute soft gaps."""
    hard_by_nutrient: dict[str, int] = {}
    soft_by_nutrient: dict[str, int] = {}
    exposure_sum: dict[str, float] = {}
    exposure_days: dict[str, int] = {}
    for day in days:
        for row in day["hard_violations"]:
            nutrient = row.get("nutrient")
            if nutrient is None:
                continue
            hard_by_nutrient[nutrient] = hard_by_nutrient.get(nutrient, 0) + 1
        for row in day["soft_gaps"]:
            if not day["completeness"]["complete"]:
                continue
            soft_by_nutrient[row["nutrient"]] = soft_by_nutrient.get(row["nutrient"], 0) + 1
        for row in day["nutrients"]:
            if not day["completeness"]["complete"]:
                continue
            exposure_sum[row["nutrient"]] = exposure_sum.get(row["nutrient"], 0.0) + row["pct_deviation"]
            exposure_days[row["nutrient"]] = exposure_days.get(row["nutrient"], 0) + 1

    mean_exposure = {
        nutrient: round(exposure_sum[nutrient] / exposure_days[nutrient], 4)
        for nutrient in sorted(exposure_sum)
    }
    complete_days = sum(1 for day in days if day["completeness"]["complete"])
    return {
        "days_logged": len(days),
        "hard_violation_days": sum(1 for d in days if not d["compliant"]),
        "hard_violations_by_nutrient": dict(sorted(hard_by_nutrient.items())),
        "soft_gaps_by_nutrient": dict(sorted(soft_by_nutrient.items())),
        "mean_pct_deviation_by_nutrient": mean_exposure,
        "complete_days": complete_days,
        "fraction_complete": round(complete_days / len(days), 4) if days else 0.0,
    }


def _theil_sen_slope(times: list[float], values: list[float]) -> float:
    n = len(values)
    slopes = [
        (values[j] - values[i]) / (times[j] - times[i])
        for i in range(n - 1)
        for j in range(i + 1, n)
        if times[j] - times[i] > 0
    ]
    return float(median(slopes)) if slopes else 0.0


def _day_offsets(dates: list[Any]) -> list[float]:
    offsets: list[float] = []
    for i, raw in enumerate(dates):
        try:
            offsets.append(float(date.fromisoformat(str(raw)).toordinal()))
        except (TypeError, ValueError):
            offsets.append(float(i))
    return offsets


def deviation_series(
    day_analyses: Iterable[Mapping[str, Any]],
    envelope: NutrientEnvelope,
) -> dict[str, dict[str, Any]]:
    """Callers must split historical days by effective envelope version."""
    constraints = sorted(envelope.targets, key=lambda c: (c.nutrient.value, c.kind.value))
    constraint_count: dict[str, int] = {}
    for constraint in constraints:
        nutrient_key = constraint.nutrient.value
        constraint_count[nutrient_key] = constraint_count.get(nutrient_key, 0) + 1

    series_by_key: dict[str, dict[str, Any]] = {}
    days = sorted(day_analyses, key=lambda d: d["date"])
    for constraint in constraints:
        nutrient = constraint.nutrient.value
        series_key = (
            nutrient
            if constraint_count[nutrient] == 1
            else f"{nutrient}:{constraint.kind.value}"
        )
        series = series_by_key.setdefault(
            series_key,
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
            else:
                exposure = abs(signed)
            points.append(
                {
                    "date": day["date"],
                    "total": round(total, 6),
                    "pct": round(signed, 4),
                    "exposure": round(exposure, 4),
                    "complete": day.get("completeness", {}).get("complete", True),
                }
            )
    return dict(sorted(series_by_key.items()))


def trend_flags(
    series: Mapping[str, Mapping[str, Any]],
    min_len: int = _MIN_SERIES_LEN,
    slope_trigger: float = _SLOPE_TRIGGER,
) -> list[dict[str, Any]]:
    """Input points must be chronological. Only complete days enter trends."""
    flags: list[dict[str, Any]] = []
    for series_key in sorted(series):
        s = series[series_key]
        points = [p for p in s["points"] if p.get("complete", True)]
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
                "nutrient": s["nutrient"],
                "series_key": series_key,
                "kind": s["kind"],
                "slope_pct_per_day": round(slope, 4),
                "direction": direction,
                "severity": "alert" if alert else "review",
                "latest_exposure_pct": round(latest, 4),
                "projected_3d_exposure_pct": round(projected, 4),
                "reason": (
                    f"{series_key} deviation {direction} at {slope:+.2f} pct-points/day "
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
    """Apply one envelope to every logged date. Callers own approval coverage."""
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
    "aggregate_days",
    "analyse_day",
    "analyse_patient",
    "analyse_range",
    "classify_constraint",
    "day_totals",
    "deviation_series",
    "trend_flags",
]
