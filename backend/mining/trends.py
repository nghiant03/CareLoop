from __future__ import annotations

from datetime import date

import numpy as np

_MIN_SERIES_LEN = 3

_THRESHOLDS = {
    "K": {"flag": 5.5, "urgent_now": 5.0, "unit": "mmol/L", "field": "labs_K_monthly", "serum": "serum_K_meq_L"},
    "PO4": {"flag": 5.0, "urgent_now": 4.6, "unit": "mg/dL", "field": "labs_PO4_monthly", "serum": "serum_PO4_mg_dL"},
}

_SLOPE_TRIGGER = 0.05


def _theil_sen_slope(y: list[float], times=None) -> float:
    """Use elapsed months or monthly spacing when times are omitted."""
    values = np.asarray(y, dtype=float)
    n = len(values)
    times = list(range(n)) if times is None else times
    slopes = [
        (values[j] - values[i]) / (times[j] - times[i])
        for i in range(n - 1) for j in range(i + 1, n) if times[j] > times[i]
    ]
    return float(np.median(slopes)) if slopes else 0.0


def _ewma_slope(y: list[float], halflife: float = 2.0, times=None) -> float:
    """Recent readings receive exponentially greater weight by elapsed month."""
    values = np.asarray(y, dtype=float)
    x = np.arange(len(values), dtype=float) if times is None else np.asarray(times, dtype=float)
    w = 0.5 ** ((x[-1] - x) / halflife)
    xbar = float(np.average(x, weights=w))
    ybar = float(np.average(values, weights=w))
    denom = float(np.sum(w * (x - xbar) ** 2))
    return float(np.sum(w * (x - xbar) * (values - ybar)) / denom) if denom else 0.0


def _would_flag(slope: float, latest: float, cfg: dict) -> bool:
    projected = latest + 3.0 * slope
    return bool(slope > _SLOPE_TRIGGER or (projected >= cfg["flag"] and latest < cfg["flag"]))


def _is_current_first(patient: dict, field: str, serum_field: str) -> bool:
    offsets = patient.get("months_offset_ago")
    values = patient.get(field) or []
    if (
        isinstance(offsets, list)
        and len(offsets) == len(values)
        and all(isinstance(o, (int, float)) for o in offsets)
    ):
        if offsets[0] < offsets[-1]:
            return True
        if offsets[0] > offsets[-1]:
            return False
    serum = patient.get(serum_field)
    if serum is not None and values:
        eps = 1e-6
        if abs(float(values[0]) - float(serum)) <= eps:
            return True
        if abs(float(values[-1]) - float(serum)) <= eps:
            return False
    return True


def _oldest_first(patient: dict, field: str, serum_field: str) -> list[float]:
    values = [float(v) for v in (patient.get(field) or [])]
    return values[::-1] if _is_current_first(patient, field, serum_field) else values


def detect_trends(patients: list[dict]) -> list[dict]:
    """Dated observations take precedence. EWMA never deescalates an urgent latest dated value."""
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
                reason = (
                    f"{analyte} projected {projected:.2f} crosses the "
                    f"{cfg['flag']} {cfg['unit']} threshold within 3 months "
                    f"(slope {slope:+.3f} {cfg['unit']}/month, latest {latest:.2f})"
                )
            else:
                # An urgent value alone does not establish a measured rise.
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
