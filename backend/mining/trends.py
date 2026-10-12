"""Longitudinal lab trend detection (K+ and PO4).

Dated observations take precedence per analyte and use elapsed months of
30.4375 days. Fixture arrays otherwise use one-month spacing. Infer their
orientation from offsets, then serum-value matching; default to newest-first.
Returned series are oldest-first. Theil-Sen uses median pairwise slopes.

Flagging rules
--------------
* Potassium (mmol/L/month): slope > 0.05 OR 3-month projection crossing 5.5.
* Phosphate (mg/dL/month): slope > 0.05 OR 3-month projection crossing 5.0.
* Dated observations also flag an urgent latest value, even in a sparse series.
* Flag reasons name the actual trigger — slope, projected crossing, or the
  alert-level value — instead of assuming a rise.
* initial severity: "urgent" if the latest value reaches the clinical alert
  level (K+ >= 5.0, PO4 >= 4.6) or the 3-month projection crosses the flag
  threshold; otherwise "review".

EWMA-weighted least squares gives recent readings more weight with a two-month
half-life. Downgrade an urgent trend to review when EWMA no longer satisfies
the flag rule, since the full-window rise may have plateaued. An urgent latest
dated observation remains urgent regardless of slope support.
"""

from __future__ import annotations

from datetime import date

import numpy as np

_MIN_SERIES_LEN = 3

# Concentration thresholds and corresponding fixture/observation fields.
_THRESHOLDS = {
    "K": {"flag": 5.5, "urgent_now": 5.0, "unit": "mmol/L", "field": "labs_K_monthly", "serum": "serum_K_meq_L"},
    "PO4": {"flag": 5.0, "urgent_now": 4.6, "unit": "mg/dL", "field": "labs_PO4_monthly", "serum": "serum_PO4_mg_dL"},
}

_SLOPE_TRIGGER = 0.05


def _theil_sen_slope(y: list[float], times=None) -> float:
    """Median pairwise concentration slope per month; skip nonpositive intervals.

    ``times`` uses elapsed months. Without it, readings are one month apart.
    Return 0.0 when no positive interval exists.
    """
    values = np.asarray(y, dtype=float)
    n = len(values)
    times = list(range(n)) if times is None else times
    slopes = [
        (values[j] - values[i]) / (times[j] - times[i])
        for i in range(n - 1) for j in range(i + 1, n) if times[j] > times[i]
    ]
    return float(np.median(slopes)) if slopes else 0.0


def _ewma_slope(y: list[float], halflife: float = 2.0, times=None) -> float:
    """Exponentially weighted least-squares slope with more weight on recent months.

    ``times`` uses elapsed months; omitted times assume monthly readings.
    Weights decay with a half-life of ``halflife`` months. Return 0.0 when
    the weighted time variance is zero. Input must contain at least one reading.
    """
    values = np.asarray(y, dtype=float)
    x = np.arange(len(values), dtype=float) if times is None else np.asarray(times, dtype=float)
    w = 0.5 ** ((x[-1] - x) / halflife)
    xbar = float(np.average(x, weights=w))
    ybar = float(np.average(values, weights=w))
    denom = float(np.sum(w * (x - xbar) ** 2))
    return float(np.sum(w * (x - xbar) * (values - ybar)) / denom) if denom else 0.0


def _would_flag(slope: float, latest: float, cfg: dict) -> bool:
    """The shared flag rule: slope above trigger or 3-month projection crossing."""
    projected = latest + 3.0 * slope
    return bool(slope > _SLOPE_TRIGGER or (projected >= cfg["flag"] and latest < cfg["flag"]))


def _is_current_first(patient: dict, field: str, serum_field: str) -> bool:
    """Infer whether index 0 is the newest reading from offsets or the serum value."""
    offsets = patient.get("months_offset_ago")
    values = patient.get(field) or []
    if (
        isinstance(offsets, list)
        and len(offsets) == len(values)
        and all(isinstance(o, (int, float)) for o in offsets)
    ):
        if offsets[0] < offsets[-1]:  # e.g. [0..5]: index 0 = 0 months ago
            return True
        if offsets[0] > offsets[-1]:  # e.g. [5..0]: index 0 = oldest
            return False
    serum = patient.get(serum_field)
    if serum is not None and values:
        eps = 1e-6
        if abs(float(values[0]) - float(serum)) <= eps:
            return True
        if abs(float(values[-1]) - float(serum)) <= eps:
            return False
    return True  # dataset convention: newest-first


def _oldest_first(patient: dict, field: str, serum_field: str) -> list[float]:
    values = [float(v) for v in (patient.get(field) or [])]
    return values[::-1] if _is_current_first(patient, field, serum_field) else values


def detect_trends(patients: list[dict]) -> list[dict]:
    """Detect rising potassium / phosphate trends across patients.

    Returns a list of flags sorted by severity ("urgent" first) then slope
    (descending). Each flag: {patient_id, analyte, slope_per_month,
    ewma_slope_per_month, values (oldest->newest), projected_3mo, severity,
    reason}.

    Dated observations take precedence over fixture monthly series; elapsed
    dates determine slopes. Sparse dated series can flag an urgent latest value
    even without enough points for the usual trend rule.

    Theil-Sen raises trend flags. EWMA (half-life 2 months) can downgrade an
    urgent trend to "review" when the recent regime no longer satisfies the
    flag rule, but never de-escalates an urgent latest dated observation.
    """
    flags: list[dict] = []
    for p in patients:
        for analyte, cfg in _THRESHOLDS.items():
            observations = {o["observed_at"]: o for o in p.get("observations", [])
                            if o["metric"] == cfg["serum"]}
            dates = sorted(observations)
            series = ([observations[d]["value"] for d in dates] if dates
                      else _oldest_first(p, cfg["field"], cfg["serum"]))
            times = ([date.fromisoformat(d).toordinal() / 30.4375 for d in dates]
                     if dates else None)
            if not series or (len(series) < _MIN_SERIES_LEN and (not dates or series[-1] < cfg["urgent_now"])):
                continue
            slope = _theil_sen_slope(series, times)
            latest = series[-1]
            projected = latest + 3.0 * slope

            if not _would_flag(slope, latest, cfg) and (not dates or latest < cfg["urgent_now"]):
                continue

            # Hybrid de-escalation: the EWMA slope tracks the recent regime,
            # so a Theil-Sen flag without EWMA support may reflect an older rise.
            # An urgent dated value remains urgent.
            ewma = _ewma_slope(series, times=times)
            ewma_rising = _would_flag(ewma, latest, cfg)

            urgent = latest >= cfg["urgent_now"] or projected >= cfg["flag"]
            de_escalated = urgent and not ewma_rising and (not dates or latest < cfg["urgent_now"])
            if de_escalated:
                urgent = False

            if slope > _SLOPE_TRIGGER:
                reason = (
                    f"{analyte} rising {slope:+.3f} {cfg['unit']}/month "
                    f"(latest {latest:.2f}, 3-mo projection {projected:.2f}, "
                    f"threshold {cfg['flag']})"
                )
            elif _would_flag(slope, latest, cfg):
                # Slope below the trigger but the 3-month projection crosses
                # the flag threshold while the latest value has not.
                reason = (
                    f"{analyte} projected {projected:.2f} crosses the "
                    f"{cfg['flag']} {cfg['unit']} threshold within 3 months "
                    f"(slope {slope:+.3f} {cfg['unit']}/month, latest {latest:.2f})"
                )
            else:
                # Flagged by the urgent latest value, not by a measured rise:
                # never explain a threshold trigger as a zero "rise".
                reason = (
                    f"{analyte} {latest:.2f} {cfg['unit']} is at or above the "
                    f"clinical alert level {cfg['urgent_now']} "
                    f"(slope {slope:+.3f} {cfg['unit']}/month; no rising "
                    f"trend measured)"
                )
            if de_escalated:
                reason += (
                    f"; EWMA slope {ewma:+.3f} {cfg['unit']}/month — recent "
                    f"regime no longer rising, de-escalated to review"
                )

            flags.append(
                {
                    "patient_id": p["patient_id"],
                    "analyte": analyte,
                    "slope_per_month": round(slope, 4),
                    "ewma_slope_per_month": round(ewma, 4),
                    "values": series,
                    "observed_dates": dates,
                    "observation_id": observations[dates[-1]]["observation_id"] if dates else None,
                    "projected_3mo": round(projected, 3),
                    "severity": "urgent" if urgent else "review",
                    "reason": reason,
                }
            )

    flags.sort(key=lambda f: (0 if f["severity"] == "urgent" else 1, -f["slope_per_month"]))
    return flags
