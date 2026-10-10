"""Seeded synthetic patient generator for fixtures and demonstrations.

Produces ``N`` synthetic Singapore-relevant patients from a small set of clinical
archetypes (T2D, HTN, T2D+HTN, CKD 3, CKD 4, CKD 4+hyperkalemia, CKD 5
pre-dialysis, pregnancy [excluded], healthy control) with longitudinal monthly
serum K and phosphate values.

Reproducibility
---------------
A single integer seed drives every random draw. When NumPy is installed we use
``numpy.random.default_rng(seed)``. NumPy is a backend runtime dependency;
standalone runs without it fall back to a small stdlib ``random.Random(seed)``
shim that mirrors the subset
of the ``Generator`` API we use (``normal``/``uniform``/``integers``/``choice``/
``random``). Output is reproducible for a fixed seed, selected RNG backend,
and Python/NumPy version; the two RNG backends do not promise identical output.

Usage
-----
    python -m data.patients_generator --n 20 --seed 0 --out data/patients.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Optional

from data.patient import Patient


# ---------------------------------------------------------------------------
# RNG abstraction
# ---------------------------------------------------------------------------


class _StdlibRNG:
    """Minimal stand-in for ``numpy.random.Generator`` used by this generator.

    Mirrors numpy semantics for the methods we call, in particular
    ``integers(low, high)`` with an *exclusive* high bound.
    """

    def __init__(self, seed: Optional[int]) -> None:
        self._r = random.Random(seed)

    def random(self) -> float:
        return self._r.random()

    def normal(self, loc: float = 0.0, scale: float = 1.0) -> float:
        return self._r.gauss(loc, scale)

    def uniform(self, low: float = 0.0, high: float = 1.0) -> float:
        return self._r.uniform(low, high)

    def integers(self, low: int, high: Optional[int] = None) -> int:
        if high is None:
            low, high = 0, low
        return self._r.randrange(low, high)

    def choice(self, a, p=None):
        seq = list(a)
        if p is not None:
            return self._r.choices(seq, weights=list(p), k=1)[0]
        return self._r.choice(seq)


_NUMPY_NOTICE_SHOWN = False


def get_rng(seed: Optional[int]):
    """Return a numpy Generator when available, else the stdlib shim."""
    global _NUMPY_NOTICE_SHOWN
    try:  # pragma: no cover - depends on environment
        import numpy as np  # type: ignore

        return np.random.default_rng(seed), "numpy.random.default_rng"
    except Exception:  # noqa: BLE001 - numpy is optional
        if not _NUMPY_NOTICE_SHOWN:
            print(
                "[patients_generator] numpy not available; using deterministic "
                "stdlib random.Random shim (same seed still reproducible).",
                file=sys.stderr,
            )
            _NUMPY_NOTICE_SHOWN = True
        return _StdlibRNG(seed), "stdlib.random.Random"


# ---------------------------------------------------------------------------
# Clinical archetypes
# ---------------------------------------------------------------------------
# Each archetype is a dict of distribution parameters. Ranges are (mean, sd).
# ``k_trend`` / ``po4_trend`` are the total drift across the 6-month window
# (recent value minus oldest value); positive => rising trend.

ARCHETYPES: dict[str, dict[str, Any]] = {
    "T2D": {
        "diagnoses": ["T2D"],
        "egfr": (85.0, 6.0),
        "k": (4.0, 0.15),
        "k_trend": 0.05,
        "po4": (3.5, 0.25),
        "po4_trend": 0.05,
        "meds": ["metformin"],
        "age": (58.0, 8.0),
        "weight": (72.0, 10.0),
        "height": (165.0, 8.0),
        "hba1c": 7.2,
        "sbp": (128.0, 8.0),
        "dbp": (80.0, 6.0),
        "exclude": False,
    },
    "HTN": {
        "diagnoses": ["HTN"],
        "egfr": (85.0, 7.0),
        "k": (4.2, 0.15),
        "k_trend": 0.05,
        "po4": (3.5, 0.25),
        "po4_trend": 0.05,
        "meds": ["ACEi"],
        "age": (62.0, 9.0),
        "weight": (70.0, 11.0),
        "height": (164.0, 8.0),
        "hba1c": 5.6,
        "sbp": (145.0, 10.0),
        "dbp": (88.0, 7.0),
        "exclude": False,
    },
    "T2D_HTN": {
        "diagnoses": ["T2D", "HTN"],
        "egfr": (82.0, 8.0),
        "k": (4.1, 0.18),
        "k_trend": 0.08,
        "po4": (3.6, 0.25),
        "po4_trend": 0.08,
        "meds": ["metformin", "ACEi"],
        "age": (63.0, 8.0),
        "weight": (74.0, 12.0),
        "height": (165.0, 8.0),
        "hba1c": 7.5,
        "sbp": (142.0, 10.0),
        "dbp": (86.0, 7.0),
        "exclude": False,
    },
    "CKD3_T2D_HTN": {
        "diagnoses": ["T2D", "HTN", "CKD_stage_3"],
        "egfr": (45.0, 6.0),
        "k": (4.5, 0.22),
        "k_trend": 0.15,
        "po4": (3.9, 0.3),
        "po4_trend": 0.15,
        "meds": ["metformin", "ACEi", "statin"],
        "age": (67.0, 8.0),
        "weight": (73.0, 12.0),
        "height": (164.0, 8.0),
        "hba1c": 7.0,
        "sbp": (140.0, 11.0),
        "dbp": (84.0, 7.0),
        "exclude": False,
    },
    "CKD4_T2D_HTN": {
        "diagnoses": ["T2D", "HTN", "CKD_stage_4"],
        "egfr": (28.0, 5.0),
        "k": (5.0, 0.28),
        "k_trend": 0.35,
        "po4": (4.6, 0.45),
        "po4_trend": 0.35,
        "meds": ["insulin", "ACEi", "statin", "phosphate_binder"],
        "age": (70.0, 8.0),
        "weight": (70.0, 12.0),
        "height": (163.0, 8.0),
        "hba1c": 7.3,
        "sbp": (150.0, 12.0),
        "dbp": (88.0, 8.0),
        "exclude": False,
    },
    "CKD4_hyperK": {
        "diagnoses": ["T2D", "CKD_stage_4", "hyperkalemia"],
        "egfr": (26.0, 5.0),
        "k": (5.6, 0.22),
        "k_trend": 0.55,
        "po4": (4.9, 0.45),
        "po4_trend": 0.4,
        "meds": ["insulin", "ACEi", "statin", "phosphate_binder", "potassium_binder"],
        "age": (71.0, 7.0),
        "weight": (68.0, 11.0),
        "height": (162.0, 8.0),
        "hba1c": 7.6,
        "sbp": (152.0, 12.0),
        "dbp": (88.0, 8.0),
        "exclude": False,
    },
    "CKD5_pre_dialysis_hyperPO4": {
        "diagnoses": ["CKD_stage_5_pre_dialysis"],
        "egfr": (18.0, 3.0),
        "k": (5.0, 0.25),
        "k_trend": 0.3,
        "po4": (6.5, 0.6),
        "po4_trend": 0.6,
        "meds": ["phosphate_binder", "erythropoietin", "statin"],
        "age": (68.0, 9.0),
        "weight": (66.0, 11.0),
        "height": (162.0, 8.0),
        "hba1c": 6.4,
        "sbp": (148.0, 12.0),
        "dbp": (86.0, 8.0),
        "exclude": False,
    },
    "pregnancy_T2D": {
        "diagnoses": ["pregnancy", "T2D"],
        "egfr": (90.0, 6.0),
        "k": (4.0, 0.15),
        "k_trend": 0.0,
        "po4": (3.5, 0.25),
        "po4_trend": 0.0,
        "meds": ["insulin"],
        "age": (31.0, 4.0),
        "weight": (68.0, 9.0),
        "height": (160.0, 6.0),
        "hba1c": 6.5,
        "sbp": (118.0, 8.0),
        "dbp": (74.0, 6.0),
        "exclude": True,
    },
    "healthy_control": {
        "diagnoses": [],
        "egfr": (95.0, 5.0),
        "k": (4.0, 0.15),
        "k_trend": 0.0,
        "po4": (3.4, 0.25),
        "po4_trend": 0.0,
        "meds": [],
        "age": (45.0, 12.0),
        "weight": (65.0, 10.0),
        "height": (166.0, 8.0),
        "hba1c": 5.3,
        "sbp": (118.0, 7.0),
        "dbp": (76.0, 6.0),
        "exclude": False,
    },
}

ARCHETYPE_ORDER = list(ARCHETYPES.keys())


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _longitudinal(
    rng,
    current: float,
    total_trend: float,
    monthly_sd: float,
    lo: float,
    hi: float,
    n_months: int = 6,
) -> list[float]:
    """Return ``n_months`` values, index 0 = most recent.

    ``current`` is the most-recent value; older values step back by
    ``total_trend`` across the window (positive => rising trend).
    """
    out: list[float] = []
    for i in range(n_months):
        base = current - total_trend * (i / (n_months - 1))
        noise = rng.normal(0.0, monthly_sd)
        out.append(round(_clip(base + noise, lo, hi), 2))
    # Anchor the current value exactly to the requested target.
    out[0] = round(_clip(current, lo, hi), 2)
    return out


def make_patient(rng, index: int, archetype: str) -> Patient:
    spec = ARCHETYPES[archetype]
    pid = f"P{index:04d}"

    sex = "F" if archetype == "pregnancy_T2D" else ("F" if rng.random() < 0.5 else "M")

    height = round(_clip(rng.normal(*spec["height"]), 140.0, 200.0), 1)
    weight = round(_clip(rng.normal(*spec["weight"]), 35.0, 160.0), 1)
    bmi = round(weight / ((height / 100.0) ** 2), 1)

    age = int(round(_clip(rng.normal(*spec["age"]), 18.0, 95.0)))
    egfr = round(_clip(rng.normal(*spec["egfr"]), 3.0, 130.0), 1)

    k_current = round(_clip(rng.normal(*spec["k"]), 2.5, 7.0), 2)
    po4_current = round(_clip(rng.normal(*spec["po4"]), 1.5, 9.0), 2)

    labs_k = _longitudinal(rng, k_current, spec["k_trend"], 0.12, 2.5, 7.0)
    labs_po4 = _longitudinal(rng, po4_current, spec["po4_trend"], 0.15, 1.5, 9.0)

    hba1c = round(_clip(spec["hba1c"] + rng.normal(0.0, 0.4), 4.5, 12.0), 1)
    sbp = int(round(_clip(rng.normal(*spec["sbp"]), 90.0, 200.0)))
    dbp = int(round(_clip(rng.normal(*spec["dbp"]), 50.0, 120.0)))

    return Patient(
        patient_id=pid,
        age=age,
        sex=sex,
        weight_kg=weight,
        diagnoses=list(spec["diagnoses"]),
        egfr=egfr,
        serum_K_meq_L=labs_k[0],
        serum_PO4_mg_dL=labs_po4[0],
        meds=list(spec["meds"]),
        archetype=archetype,
        exclude_from_careloop=bool(spec["exclude"]),
        height_cm=height,
        bmi=bmi,
        hba1c_pct=hba1c,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        labs_K_monthly=labs_k,
        labs_PO4_monthly=labs_po4,
        months_offset_ago=[0, 1, 2, 3, 4, 5],
        notes=(
            "Out of scope for CareLoop (pregnancy)."
            if spec["exclude"]
            else None
        ),
    )


def generate(n: int, seed: Optional[int]) -> list[Patient]:
    """Generate ``n`` patients by cycling through all archetypes."""
    if n < 0:
        raise ValueError("n must be >= 0")
    rng, _backend = get_rng(seed)
    patients: list[Patient] = []
    for i in range(n):
        archetype = ARCHETYPE_ORDER[i % len(ARCHETYPE_ORDER)]
        patients.append(make_patient(rng, i + 1, archetype))
    return patients


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate deterministic synthetic patients.")
    p.add_argument("--n", type=int, default=20, help="number of patients (default 20)")
    p.add_argument("--seed", type=int, default=0, help="RNG seed (default 0)")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/patients.json"),
        help="output JSON path (default data/patients.json)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    _, backend = get_rng(args.seed)
    patients = generate(args.n, args.seed)

    payload = [p.model_dump(by_alias=True) for p in patients]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"Wrote {len(payload)} patients to {args.out} "
        f"(seed={args.seed}, rng={backend}, archetypes={len(ARCHETYPE_ORDER)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
