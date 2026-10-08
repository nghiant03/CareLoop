"""Longitudinal lab trend detection (K+ and PO4).

Series orientation
------------------
The task brief assumed ``labs_*_monthly`` runs oldest->newest, but the actual
dataset is the opposite: for every patient ``labs_K_monthly[0]`` equals the
current ``serum_K_meq_L`` and ``months_offset_ago == [0, 1, 2, 3, 4, 5]``
(0 = this month). Values are therefore stored **newest-first**.

``_oldest_first`` restores chronological (oldest->newest) order using, in
order of preference:

1. ``months_offset_ago`` — ascending-from-0 means newest-first (reverse);
   descending-to-0 means already oldest-first (keep).
2. Fall back to matching ``serum_K_meq_L`` / ``serum_PO4_mg_dL`` against the
   first or last element.
3. With no signal at all, assume newest-first (the dataset convention).

Slopes are fit with Theil-Sen (median of pairwise slopes — robust to outlier
months); OLS is not used.

Flagging rules
--------------
* Potassium (mmol/L/month): slope > 0.05 OR 3-month projection crossing 5.5.
* Phosphate (mg/dL/month): slope > 0.05 OR 3-month projection crossing 5.0.
* severity: "urgent" if the latest value is already above the clinical alert
  level (K+ >= 5.0, PO4 >= 4.6) or the 3-month projection crosses the flag
  threshold; otherwise "review".

Hybrid de-escalation (COMPARISON.md §2)
---------------------------------------
The Theil-Sen slope is fit over the full window, so a series that rose and
then plateaued keeps flagging (synthetic plateau false-positive rate 14% vs
EWMA's 6%). Flags therefore stay raised by Theil-Sen exactly as before
(unchanged flag semantics), but each flag also computes the EWMA-weighted
least-squares slope (half-life 2 months, exposed as ``ewma_slope_per_month``).
If the *recent* regime no longer satisfies the same flag rule under the EWMA
slope — i.e. EWMA would not flag this series — severity is de-escalated to
"review" and the reason says so. Patients flagged by both estimators keep
their severity.
"""

from __future__ import annotations

import numpy as np

_MIN_SERIES_LEN = 3

# (flag-threshold for projected crossing, alert-now threshold, units)
_THRESHOLDS = {
    "K": {"flag": 5.5, "urgent_now": 5.0, "unit": "mmol/L", "field": "labs_K_monthly", "serum": "serum_K_meq_L"},
    "PO4": {"flag": 5.0, "urgent_now": 4.6, "unit": "mg/dL", "field": "labs_PO4_monthly", "serum": "serum_PO4_mg_dL"},
}

_SLOPE_TRIGGER = 0.05


def _theil_sen_slope(y: list[float]) -> float:
    """Median of all pairwise slopes (classic Theil-Sen estimator)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    slopes = [
        (y[j] - y[i]) / (j - i) for i in range(n - 1) for j in range(i + 1, n)
    ]
    return float(np.median(slopes))


def _ewma_slope(y: list[float], halflife: float = 2.0) -> float:
    """Exponentially weighted least-squares slope (recent months count more).

    Weights decay with a half-life of ``halflife`` months, so the estimate
    tracks the *current* regime rather than the whole history — the property
    the full-window Theil-Sen estimator lacks. Same estimator as the one
    studied in ``backend/mining/comparison.py`` (§2).
    """
    y = np.asarray(y, dtype=float)
    x = np.arange(len(y), dtype=float)
    w = 0.5 ** ((len(y) - 1 - x) / halflife)
    xbar = float(np.average(x, weights=w))
    ybar = float(np.average(y, weights=w))
    denom = float(np.sum(w * (x - xbar) ** 2))
    return float(np.sum(w * (x - xbar) * (y - ybar)) / denom)


def _would_flag(slope: float, latest: float, cfg: dict) -> bool:
    """The shared flag rule: slope above trigger or 3-month projection crossing."""
    projected = latest + 3.0 * slope
    return bool(slope > _SLOPE_TRIGGER or (projected >= cfg["flag"] and latest < cfg["flag"]))


def _is_current_first(patient: dict, field: str, serum_field: str) -> bool:
    """Decide whether the stored series is newest-first (index 0 = today)."""
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

    Flags are raised by the Theil-Sen rule; the EWMA slope (half-life 2
    months) only acts as a de-escalation signal: if the recent regime no
    longer satisfies the same flag rule under EWMA, severity is downgraded
    to "review" with a reason noting the EWMA check.
    """
    flags: list[dict] = []
    for p in patients:
        for analyte, cfg in _THRESHOLDS.items():
            series = _oldest_first(p, cfg["field"], cfg["serum"])
            if len(series) < _MIN_SERIES_LEN:
                continue
            slope = _theil_sen_slope(series)
            latest = series[-1]
            projected = latest + 3.0 * slope

            if not _would_flag(slope, latest, cfg):
                continue

            # Hybrid de-escalation: the EWMA slope tracks the recent regime,
            # so a Theil-Sen flag whose EWMA counterpart no longer fires is
            # a rise that has plateaued — downgrade to "review".
            ewma = _ewma_slope(series)
            ewma_rising = _would_flag(ewma, latest, cfg)

            urgent = latest >= cfg["urgent_now"] or projected >= cfg["flag"]
            de_escalated = urgent and not ewma_rising
            if de_escalated:
                urgent = False

            reason = (
                f"{analyte} rising {slope:+.3f} {cfg['unit']}/month "
                f"(latest {latest:.2f}, 3-mo projection {projected:.2f}, "
                f"threshold {cfg['flag']})"
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
                    "projected_3mo": round(projected, 3),
                    "severity": "urgent" if urgent else "review",
                    "reason": reason,
                }
            )

    flags.sort(key=lambda f: (0 if f["severity"] == "urgent" else 1, -f["slope_per_month"]))
    return flags