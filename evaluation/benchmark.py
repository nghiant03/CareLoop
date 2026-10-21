"""Quality/runtime: consume the existing optimiser benchmark artefacts.

Read the existing benchmark CSV and Markdown rather than running search.
``--rerun-benchmark`` regenerates them first. Include every recorded method
and keep violation rates unrounded for verdict decisions.
"""

from __future__ import annotations

import csv
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.storage_paths import artifact_dir
from evaluation.common import ROOT

__all__ = ["evaluate_benchmark", "verdict_from_headline"]

from backend.datasets.paths import dataset_dir

_CSV_PATH = dataset_dir() / "benchmarks" / "benchmark_results.csv"
_MD_PATH = dataset_dir() / "benchmarks" / "benchmark_results.md"


def _read_rows(path: Path = _CSV_PATH) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _summary_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["phase"] == "main":
            by_method[row["method"]].append(row)
    table = []
    # Include every recorded method, not a fixed comparison subset.
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
        # Rounding a nonzero rate to zero would incorrectly permit PASS.
            "violation_rate": sum(1 for v in violations if v > 0) / len(violations),
            "mean_runtime_ms": round(statistics.fmean(runtimes), 1),
            "mean_search_evaluations": statistics.fmean(float(r["evaluations"]) for r in runs) if all(r.get("evaluations") for r in runs) else None,
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


def _recommendation(path: Path = _MD_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "## Recommendation"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return "(recommendation section not found in benchmark_results.md)"


def verdict_from_headline(headline: list[dict[str, Any]]) -> tuple[str, str]:
    """Derive the benchmark verdict and its explanation from the headline table.

    The hypervolume winner has the highest mean HV across all method rows in
    the benchmark artefact, not a hardcoded algorithm identity. PASS requires
    that winner's exact, unrounded hard-constraint violation rate to be zero.
    Any violating run makes the rate nonzero and the verdict FAIL: the
    front-quality leader cannot then be recommended as-is.
    """
    if not headline:
        return ("FAIL",
                "No main-phase benchmark rows were found in the artefact, so no method comparison could be derived.")
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
    rate = winner["violation_rate"]
    rate_text = "0%" if rate == 0 else f"{rate:.3%}"
    note += f") with a {rate_text} hard-constraint violation rate."
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
        "is evaluated under Constraint satisfaction. Pymoo rows use actual-evaluation "
        "termination and record search counts; generation-boundary overshoot is "
        "possible. GA/greedy/random retain native budgets."
    )
    return verdict, note


def evaluate_benchmark(rerun_benchmark: bool = False) -> dict[str, Any]:
    """Headline optimiser benchmark table and recommendation."""
    csv_path, md_path = _CSV_PATH, _MD_PATH
    if rerun_benchmark:
        subprocess.run(
            [sys.executable, "-m", "backend.optim.benchmark"],
            cwd=str(ROOT), check=True,
            env={**os.environ, "CARELOOP_ARTIFACT_DIR": str(artifact_dir("optim").parent),
                 "CARELOOP_BENCH_SMOKE": "0"},
        )
        csv_path = artifact_dir("optim") / "benchmark_results.csv"
        md_path = artifact_dir("optim") / "benchmark_results.md"
    rows = _read_rows(csv_path)
    main_rows = [r for r in rows if r["phase"] == "main"]
    headline = _summary_table(rows)
    verdict, verdict_note = verdict_from_headline(headline)
    return {
        "criterion": "Quality/runtime (optimiser benchmark)",
        "definition": (
            f"Consumes {csv_path.parent}/benchmark_results.{{csv,md}} (4 envelopes x 5 "
            "seeds for every method recorded in the artefact, plus the pop x gen "
            "sweep). The benchmark is NOT re-run by default; pass "
            "--rerun-benchmark to regenerate it."
        ),
        "artefacts": {
            "csv": str(csv_path.relative_to(ROOT)) if csv_path.is_relative_to(ROOT) else str(csv_path),
            "md": str(md_path.relative_to(ROOT)) if md_path.is_relative_to(ROOT) else str(md_path),
            "main_runs": len(main_rows),
            "rerun_benchmark": rerun_benchmark,
        },
        "headline": headline,
        "hv_per_envelope": _hv_per_envelope(rows),
        "sweep": _sweep_table(rows),
        "recommendation": _recommendation(md_path),
        "verdict": verdict,
        "verdict_note": verdict_note,
    }
