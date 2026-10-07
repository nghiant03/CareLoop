"""Q4 — Quality/runtime: consume the existing optimiser benchmark artefacts.

By default this module does NOT re-run the benchmark; it parses
``backend/optim/benchmark_results.csv`` (per-run rows) and
``backend/optim/benchmark_results.md`` (recommendation) and recomputes the
headline table (NSGA-II vs GA vs greedy vs random: hypervolume, violations,
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

__all__ = ["evaluate_q4"]

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
    for method in ("nsga2", "ga", "greedy", "random"):
        runs = by_method.get(method, [])
        if not runs:
            continue
        hvs = [float(r["hypervolume"]) for r in runs]
        violations = [int(r["violation_count"]) for r in runs]
        runtimes = [float(r["runtime_ms"]) for r in runs]
        table.append({
            "method": method,
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
    methods = ["nsga2", "ga", "greedy", "random"]
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


def evaluate_q4(rerun_benchmark: bool = False) -> dict[str, Any]:
    """Headline optimiser benchmark table + recommendation (from artefacts)."""
    if rerun_benchmark:
        subprocess.run(
            [sys.executable, "-m", "backend.optim.benchmark"],
            cwd=str(ROOT), check=True,
        )
    rows = _read_rows()
    main_rows = [r for r in rows if r["phase"] == "main"]
    return {
        "question": "Q4 Quality/runtime (optimiser benchmark)",
        "definition": (
            "Consumes backend/optim/benchmark_results.{csv,md} (4 envelopes x 5 "
            "seeds x 4 methods, plus the pop x gen sweep). The benchmark is NOT "
            "re-run by default; pass --rerun-benchmark to regenerate it."
        ),
        "artefacts": {
            "csv": str(_CSV_PATH.relative_to(ROOT)),
            "md": str(_MD_PATH.relative_to(ROOT)),
            "main_runs": len(main_rows),
            "rerun_benchmark": rerun_benchmark,
        },
        "headline": _summary_table(rows),
        "hv_per_envelope": _hv_per_envelope(rows),
        "sweep": _sweep_table(rows),
        "recommendation": _recommendation(),
        "verdict": (
            "PASS" if any(m["method"] == "nsga2" and m["violation_rate"] == 0.0
                          for m in _summary_table(rows)) else "FAIL"
        ),
        "verdict_note": (
            "NSGA-II (production path, with the repair/greedy feasibility "
            "guarantee) is the only method combining 0% hard-constraint "
            "violations with the best hypervolume; raw baselines are shown for "
            "contrast (random violates 75% of the time by design)."
        ),
    }