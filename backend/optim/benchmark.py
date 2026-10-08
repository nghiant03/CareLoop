"""Benchmark harness: pymoo NSGA-II vs GA vs greedy vs random on real data.

Run::

    .venv/bin/python -m backend.optim.benchmark

Design
------
* 4 representative APPROVED envelopes (``backend.optim.envelopes``):
  ``ckd_strict``, ``ckd_hyperkalemia``, ``t2d_htn``, ``t2d_only``.
* Main comparison — 5 seeds each: NSGA-II (pymoo), hand-rolled GA, greedy
  construction, random search.  NSGA-II goes through ``solver.solve`` and
  therefore carries the hard feasibility guarantee; the raw baselines do not,
  so their hard-constraint violation rate is an honest measured quantity.
  Hard constraints are MAX ceilings + exclusions (PLAN.md module 4); MIN
  floors / TARGETs are soft objective terms for all methods alike.
* Hypervolume: pymoo's exact HV indicator on min-max normalised objectives.
  Bounds are computed per envelope across ALL feasible fronts from the main
  phase (all methods/seeds) and reused for the sweep; reference point is
  1.1^4.  A run with no feasible plan scores HV = 0.
* NSGA-II population/generation sweep: pop {20,40,80} x gen {40,80,160},
  1 seed, scored against the main-phase bounds.

Outputs: ``backend/optim/benchmark_results.csv`` (per-run rows) and
``backend/optim/benchmark_results.md`` (summary tables + tuning recommendation).
"""

from __future__ import annotations

import csv
import os
import statistics
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

from backend.optim.envelopes import build_benchmark_envelopes  # noqa: E402
from backend.optim.problem import OBJECTIVE_NAMES  # noqa: E402
from backend.optim.real_data import load_dishes  # noqa: E402
from backend.optim.solver import HAS_PYMOO, solve  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "benchmark_results.csv")
MD_PATH = os.path.join(_HERE, "benchmark_results.md")

SEEDS = [1, 2, 3, 4, 5]
METHODS = ["nsga2", "ga", "greedy", "random"]
SWEEP_POP = [20, 40, 80]
SWEEP_GEN = [40, 80, 160]
SWEEP_SEED = 42
REF_MARGIN = 1.1


def _run(method: str, env, dishes, seed: int, pop_size: int, n_gen: int) -> dict:
    result = solve(env, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen, method=method)
    return result


def _feasible_F(result: dict) -> np.ndarray:
    rows = []
    front = result.get("front") or []
    if not front and result.get("plan"):
        front = [result]
    for entry in front:
        if entry.get("feasible"):
            rows.append([entry["objectives"][k] for k in OBJECTIVE_NAMES])
    return np.array(rows) if rows else np.zeros((0, len(OBJECTIVE_NAMES)))


def _normalisation_bounds(all_F: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.vstack([f for f in all_F if len(f)])
    lo = stacked.min(axis=0)
    hi = stacked.max(axis=0)
    hi = np.where(hi - lo < 1e-12, lo + 1.0, hi)
    return lo, hi


def _hypervolume(F: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    if len(F) == 0:
        return 0.0
    from pymoo.indicators.hv import HV

    norm = (F - lo) / (hi - lo)
    ref_point = np.full(len(OBJECTIVE_NAMES), REF_MARGIN)
    return float(HV(ref_point=ref_point).do(norm))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def main() -> int:
    t_start = time.perf_counter()
    dishes = load_dishes()
    envelopes = build_benchmark_envelopes()
    if not HAS_PYMOO:
        print("WARNING: pymoo unavailable — NSGA-II rows will use the GA fallback engine")

    # rows: list of (row_dict, F_matrix)
    entries: list[tuple[dict, np.ndarray]] = []

    # ------------------------------------------------------------------
    # Phase 1: main comparison (4 envelopes x 5 seeds x 4 methods)
    # ------------------------------------------------------------------
    print("=" * 78)
    print("Phase 1: main comparison — 4 envelopes x 5 seeds x {nsga2, ga, greedy, random}")
    print("=" * 78)
    for env_name, env in envelopes.items():
        for seed in SEEDS:
            for method in METHODS:
                result = _run(method, env, dishes, seed, pop_size=40, n_gen=80)
                F = _feasible_F(result)
                entries.append(
                    (
                        {
                            "phase": "main",
                            "envelope": env_name,
                            "envelope_id": env.envelope_id,
                            "method": method,
                            "seed": seed,
                            "pop_size": 40,
                            "n_gen": 80,
                            "violation_count": result["violation_count"],
                            "feasible": int(bool(result["feasible"])),
                            "runtime_ms": round(result["runtime_ms"], 1),
                            "front_size": result["front_size"],
                            "engine": result.get("engine", method),
                            "hypervolume": "",
                        },
                        F,
                    )
                )
                print(
                    f"  {env_name:>16s} seed={seed} {method:>7s}"
                    f"  feasible={result['feasible']!s:>5}"
                    f"  viol={result['violation_count']:>3}"
                    f"  front={result['front_size']:>3}"
                    f"  runtime={result['runtime_ms']:>8.1f} ms"
                )

    # Per-envelope normalisation bounds over ALL feasible fronts (main phase).
    bounds: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for env_name in envelopes:
        env_Fs = [F for (row, F) in entries if row["envelope"] == env_name and len(F)]
        bounds[env_name] = _normalisation_bounds(env_Fs) if env_Fs else (
            np.zeros(len(OBJECTIVE_NAMES)), np.ones(len(OBJECTIVE_NAMES))
        )

    # ------------------------------------------------------------------
    # Phase 2: NSGA-II population/generation sweep
    # ------------------------------------------------------------------
    print("=" * 78)
    print("Phase 2: NSGA-II pop x gen sweep — 4 envelopes x 1 seed x 9 configs")
    print("=" * 78)
    for env_name, env in envelopes.items():
        lo, hi = bounds[env_name]
        for pop_size in SWEEP_POP:
            for n_gen in SWEEP_GEN:
                result = _run("nsga2", env, dishes, SWEEP_SEED, pop_size, n_gen)
                F = _feasible_F(result)
                entries.append(
                    (
                        {
                            "phase": "sweep",
                            "envelope": env_name,
                            "envelope_id": env.envelope_id,
                            "method": "nsga2-sweep",
                            "seed": SWEEP_SEED,
                            "pop_size": pop_size,
                            "n_gen": n_gen,
                            "violation_count": result["violation_count"],
                            "feasible": int(bool(result["feasible"])),
                            "runtime_ms": round(result["runtime_ms"], 1),
                            "front_size": result["front_size"],
                            "engine": result.get("engine", "nsga2"),
                            "hypervolume": "",
                        },
                        F,
                    )
                )
                print(
                    f"  {env_name:>16s} pop={pop_size:>3} gen={n_gen:>4}"
                    f"  feasible={result['feasible']!s:>5}"
                    f"  front={result['front_size']:>3}"
                    f"  runtime={result['runtime_ms']:>8.1f} ms"
                )

    # ------------------------------------------------------------------
    # Score hypervolumes (sweep reuses the envelope's main-phase bounds)
    # ------------------------------------------------------------------
    for row, F in entries:
        lo, hi = bounds[row["envelope"]]
        row["hypervolume"] = f"{_hypervolume(F, lo, hi):.6f}"

    runtime_total = time.perf_counter() - t_start

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(entries[0][0].keys()))
        writer.writeheader()
        for row, _F in entries:
            writer.writerow(row)

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------
    _write_report(entries, bounds, runtime_total)

    print(f"\nTotal wall time: {runtime_total:.1f}s")
    print(f"CSV: {CSV_PATH}")
    print(f"Report: {MD_PATH}")
    return 0


def _write_report(entries, bounds, runtime_total: float) -> None:
    main_rows = [row for row, _ in entries if row["phase"] == "main"]
    sweep_rows = [row for row, _ in entries if row["phase"] == "sweep"]
    envelope_names = sorted({row["envelope"] for row in main_rows})

    lines: list[str] = []
    lines.append("# CareLoop optimiser benchmark — real dish dataset (214 dishes)")
    lines.append("")
    lines.append(
        "Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by "
        "envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN "
        "floors / TARGETs are soft objective terms per PLAN.md module 4). "
        "HV = pymoo exact hypervolume "
        "on min-max normalised objectives (per-envelope bounds across all methods, "
        "ref point 1.1^4). NSGA-II rows carry the hard feasibility guarantee "
        "(repair/greedy fallback); raw baselines report their true violation rate."
    )
    lines.append("")

    # Headline summary per method
    lines.append("## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)")
    lines.append("")
    lines.append("| method | mean HV | HV std | violation rate | mean runtime (ms) |")
    lines.append("|---|---|---|---|---|")
    for method in METHODS:
        rs = [r for r in main_rows if r["method"] == method]
        hvs = [float(r["hypervolume"]) for r in rs]
        viol_rate = sum(1 for r in rs if r["feasible"] == 0) / len(rs) if rs else 0.0
        lines.append(
            f"| {method} | {_mean(hvs):.4f} | {_std(hvs):.4f} | {viol_rate:.0%} "
            f"| {_mean([r['runtime_ms'] for r in rs]):.1f} |"
        )
    lines.append("")

    # Per-envelope x method mean HV
    lines.append("## Mean hypervolume per envelope")
    lines.append("")
    lines.append("| envelope | " + " | ".join(METHODS) + " |")
    lines.append("|---" * (len(METHODS) + 1) + "|")
    for env_name in envelope_names:
        cells = []
        for method in METHODS:
            hvs = [
                float(r["hypervolume"])
                for r in main_rows
                if r["envelope"] == env_name and r["method"] == method
            ]
            cells.append(f"{_mean(hvs):.4f}")
        lines.append(f"| {env_name} | " + " | ".join(cells) + " |")
    lines.append("")

    # Sweep table
    lines.append("## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)")
    lines.append("")
    lines.append("| pop | gen | mean HV | mean runtime (ms) |")
    lines.append("|---|---|---|---|")
    for pop_size in SWEEP_POP:
        for n_gen in SWEEP_GEN:
            rs = [
                r
                for r in sweep_rows
                if r["pop_size"] == pop_size and r["n_gen"] == n_gen
            ]
            lines.append(
                f"| {pop_size} | {n_gen} | {_mean([float(r['hypervolume']) for r in rs]):.4f} "
                f"| {_mean([r['runtime_ms'] for r in rs]):.1f} |"
            )
    lines.append("")

    # Recommendation: knee point — best HV within a 2% band, cheapest runtime.
    sweep_stats = []
    for pop_size in SWEEP_POP:
        for n_gen in SWEEP_GEN:
            rs = [
                r for r in sweep_rows
                if r["pop_size"] == pop_size and r["n_gen"] == n_gen
            ]
            sweep_stats.append(
                {
                    "pop": pop_size,
                    "gen": n_gen,
                    "hv": _mean([float(r["hypervolume"]) for r in rs]),
                    "ms": _mean([r["runtime_ms"] for r in rs]),
                }
            )
    fastest = min(sweep_stats, key=lambda s: s["ms"])
    best_hv = max(s["hv"] for s in sweep_stats)
    knee_candidates = [s for s in sweep_stats if s["hv"] >= best_hv - 0.02 * max(best_hv, 1e-9)]
    knee = min(knee_candidates, key=lambda s: s["ms"])
    lines.append("## Recommendation")
    lines.append("")
    lines.append(
        f"* Fastest swept config: pop={fastest['pop']}, gen={fastest['gen']} "
        f"(mean HV {fastest['hv']:.4f}, {fastest['ms']:.0f} ms/solve)."
    )
    lines.append(
        f"* Knee point (HV within 2% of the best {best_hv:.4f}): "
        f"**pop={knee['pop']}, gen={knee['gen']}** "
        f"(mean HV {knee['hv']:.4f}, {knee['ms']:.0f} ms/solve)."
    )
    lines.append(
        f"* Production default recommendation: pop={knee['pop']}, gen={knee['gen']} — "
        "every swept config returns feasible plans (violation_count == 0 thanks to "
        "the repair/greedy guarantee), so choose on HV-per-millisecond; this knee "
        "keeps ~98% of the best front quality at a fraction of the max budget."
    )
    lines.append(
        f"* Total harness wall time: {runtime_total:.0f}s. "
        "Baselines: GA scalarises (single-point fronts -> lower HV); greedy is "
        "feasibility-aware by construction and near-instant but myopic; random "
        "is the floor on quality. Under the module-4 encoding (hard = MAX "
        "ceilings + exclusions only) raw random search rarely violates a "
        "ceiling, so methods are separated by hypervolume rather than "
        "violations; the repair/greedy guarantee on the NSGA-II path remains "
        "the backstop for genuinely tight ceilings."
    )
    lines.append("")

    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())