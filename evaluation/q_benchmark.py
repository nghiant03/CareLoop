"""Q4 — Quality/runtime: consume the existing optimiser benchmark artefacts.

By default this module does NOT re-run the benchmark; it parses
``backend/optim/benchmark_results.csv`` (per-run rows) and
``backend/optim/benchmark_results.md`` (recommendation) and recomputes the
headline table (all methods recorded in the artefact: hypervolume, violations,
runtime).  ``--rerun-benchmark`` re-executes ``backend.optim.benchmark``
(~21s) and re-reads the artefacts.
"""

from __future__ import annotations

import csv
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.common import ROOT

__all__ = ["evaluate_q4", "verdict_from_headline"]

_CSV_PATH = ROOT / "backend" / "optim" / "benchmark_results.csv"
_MD_PATH = ROOT / "backend" / "optim" / "benchmark_results.md"


def _read_rows() -> list[dict[str, str]]:
    with open(_CSV_PATH, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _summary_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["phase"] == "main":
            by_method[row["method"]].append(row)
    table = []
    # Every method recorded in the artefact, in a stable order — no hardcoded
    # subset (the benchmark tracks more algorithms than the original four).
    for method in sorted(by_method):
        runs = by_method[method]
        hvs = [float(r["hypervolume"]) for r in runs]
        violations = [int(r["violation_count"]) for r in runs]
        runtimes = [float(r["runtime_ms"]) for r in runs]
        guaranteed = all(r.get("guaranteed", "1") == "1" for r in runs)
        table.append({
            "method": method,
            "guarantee": "yes" if guaranteed else "no",
            "runs": len(runs),
            "mean_hv": round(statistics.fmean(hvs), 4),
            "hv_std": round(statistics.pstdev(hvs), 4) if len(hvs) > 1 else 0.0,
            "violation_rate": round(sum(1 for v in violations if v > 0) / len(violations), 3),
            "mean_runtime_ms": round(statistics.fmean(runtimes), 1),
        })
    return table


def _hv_per_envelope(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row["phase"] == "main":
            grouped[(row["envelope"], row["method"])].append(float(row["hypervolume"]))
    envelopes = sorted({k[0] for k in grouped})
    methods = sorted({k[1] for k in grouped})
    table = []
    for env in envelopes:
        entry: dict[str, Any] = {"envelope": env}
        for method in methods:
            values = grouped.get((env, method))
            entry[method] = round(statistics.fmean(values), 4) if values else None
        table.append(entry)
    return table


def _sweep_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    sweep = [r for r in rows if r["phase"] == "sweep"]
    grouped: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
    for row in sweep:
        grouped[(int(row["pop_size"]), int(row["n_gen"]))].append(row)
    table = []
    for (pop, gen), runs in sorted(grouped.items()):
        table.append({
            "pop": pop,
            "gen": gen,
            "mean_hv": round(statistics.fmean(float(r["hypervolume"]) for r in runs), 4),
            "mean_runtime_ms": round(statistics.fmean(float(r["runtime_ms"]) for r in runs), 1),
        })
    return table


def _recommendation() -> str:
    text = _MD_PATH.read_text(encoding="utf-8")
    marker = "## Recommendation"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return "(recommendation section not found in benchmark_results.md)"


def verdict_from_headline(headline: list[dict[str, Any]]) -> tuple[str, str]:
    """Derive the Q4 verdict and its explanation from the headline table.

    The hypervolume winner is computed from the data (highest mean HV across
    every method row in the benchmark artefact) — it is never hardcoded to a
    particular algorithm.  PASS requires the HV winner to also report a 0%
    hard-constraint violation rate; otherwise the front-quality leader cannot
    be recommended as-is and the verdict is FAIL.
    """
    if not headline:
        return ("FAIL",
                "No main-phase benchmark rows were found in the artefact, so "
                "no method comparison could be derived.")
    winner = max(headline, key=lambda m: (m["mean_hv"], -m["violation_rate"],
                                          m["guarantee"] == "yes"))
    runner_up = max((m for m in headline if m is not winner),
                    key=lambda m: m["mean_hv"], default=None)
    clean = winner["violation_rate"] == 0.0
    verdict = "PASS" if clean else "FAIL"

    note = (
        f"{winner['method']} leads the benchmark on mean hypervolume "
        f"({winner['mean_hv']:.4f}"
    )
    if runner_up is not None:
        if runner_up["mean_hv"] == winner["mean_hv"]:
            note += f", level with {runner_up['method']}"
        else:
            note += f", ahead of {runner_up['method']} at {runner_up['mean_hv']:.4f}"
    note += f") with a {winner['violation_rate']:.0%} hard-constraint violation rate."
    if clean:
        note += (
            " The winner claim is computed from the committed artefact rows "
            "for every recorded method, not hardcoded to any algorithm."
        )
    else:
        note += (
            " Because the front-quality leader violates hard constraints in "
            "some runs, no violation-free method leads the raw comparison; "
            "the repair/greedy guarantee fences the delivered plan, but a "
            "violation-free HV winner is required for a PASS."
        )
    note += (
        " Caveats: HV scores the whole Pareto front (front coverage) — "
        "single-point baselines (GA, greedy) are structurally disadvantaged on "
        "full-front HV, and the quality of the single delivered meal plan "
        "answers a different question (see Q3). Nominal population x "
        "generations is not an equal-work budget across all methods (e.g. "
        "MOEA/D's population is tied to its reference-direction count), and "
        "evaluation counts are estimated from the algorithm configuration "
        "rather than recorded per run."
    )
    return verdict, note


def evaluate_q4(rerun_benchmark: bool = False) -> dict[str, Any]:
    """Headline optimiser benchmark table + recommendation (from artefacts)."""
    if rerun_benchmark:
        subprocess.run(
            [sys.executable, "-m", "backend.optim.benchmark"],
            cwd=str(ROOT), check=True,
        )
    rows = _read_rows()
    main_rows = [r for r in rows if r["phase"] == "main"]
    headline = _summary_table(rows)
    verdict, verdict_note = verdict_from_headline(headline)
    return {
        "question": "Q4 Quality/runtime (optimiser benchmark)",
        "definition": (
            "Consumes backend/optim/benchmark_results.{csv,md} (4 envelopes x 5 "
            "seeds for every method recorded in the artefact, plus the pop x gen "
            "sweep). The benchmark is NOT re-run by default; pass "
            "--rerun-benchmark to regenerate it."
        ),
        "artefacts": {
            "csv": str(_CSV_PATH.relative_to(ROOT)),
            "md": str(_MD_PATH.relative_to(ROOT)),
            "main_runs": len(main_rows),
            "rerun_benchmark": rerun_benchmark,
        },
        "headline": headline,
        "hv_per_envelope": _hv_per_envelope(rows),
        "sweep": _sweep_table(rows),
        "recommendation": _recommendation(),
        "verdict": verdict,
        "verdict_note": verdict_note,
    }