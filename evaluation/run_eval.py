"""Evaluation orchestrator: runs Q1-Q6, writes results.json + EVALUATION.md.

Usage::

    .venv/bin/python -m evaluation.run            # full suite
    .venv/bin/python -m evaluation.run --rerun-benchmark
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.common import ROOT, load_patients
from evaluation.q_ablation import evaluate_q6
from evaluation.q_benchmark import evaluate_q4
from evaluation.q_conflicts import evaluate_q2
from evaluation.q_groundedness import evaluate_q5
from evaluation.q_satisfaction import evaluate_q3
from evaluation.q_traceability import evaluate_q1
from evaluation.report import render_report
from backend.storage_paths import artifact_dir

__all__ = ["main", "run_suite"]


def _run_vcs(command: list[str]) -> str | None:
    """Run a VCS command in ROOT; ``None`` on failure or missing executable."""
    import subprocess

    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None  # executable missing or not executable
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _source_revision() -> str:
    """Best-effort source revision: jj first, then git, else an explicit marker.

    The revision is report metadata, so an unavailable VCS must never abort
    the suite — that would discard every already-computed question result.
    """
    revision = _run_vcs(
        ["jj", "--ignore-working-copy", "log", "-r", "@",
         "--no-graph", "-T", "commit_id"]
    )
    if revision is None:
        revision = _run_vcs(["git", "rev-parse", "HEAD"])
    return revision or "unavailable (no accessible VCS revision)"


def run_suite(rerun_benchmark: bool = False,
              optimiser_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run all six question modules and return the combined results dict."""
    from backend.optim.real_data import load_dishes

    optimiser_kwargs = optimiser_kwargs or {}
    patients = load_patients()

    q1 = evaluate_q1(patients)
    q2 = evaluate_q2()

    dishes = load_dishes()
    q3 = evaluate_q3(patients, dishes=dishes, **optimiser_kwargs)

    q4 = evaluate_q4(rerun_benchmark=rerun_benchmark)

    from backend.app.core.kb_loader import get_kb
    q5 = evaluate_q5(get_kb())

    q6 = evaluate_q6(patients, dishes=dishes, **q6_kwargs(optimiser_kwargs))

    import hashlib
    import platform

    revision = _source_revision()
    source_paths = sorted(p for directory in ("backend", "shared", "rules", "evaluation")
                          for p in (ROOT / directory).rglob("*.py"))
    code_hash = hashlib.sha256()
    for path in source_paths:
        code_hash.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())

    return {
        "meta": {
            "suite": "CareLoop automated evaluation v1",
            "seed": optimiser_kwargs.get("seed", 42),
            "pop_size": optimiser_kwargs.get("pop_size", 40),
            "n_gen": optimiser_kwargs.get("n_gen", 80),
            "patients": len(patients),
            "dishes": len(dishes),
            "source_revision": revision,
            "working_code_sha256": code_hash.hexdigest(),
            "data_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in ("data/dishes.json", "data/patients.json", "rules/rules.json")},
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        },
        "q1_traceability": q1,
        "q2_conflicts": q2,
        "q3_constraint_satisfaction": q3,
        "q4_benchmark": q4,
        "q5_groundedness": q5,
        "q6_ablation": q6,
    }


def q6_kwargs(optimiser_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Map the shared optimiser budget onto Q6's parameters.

    Seeds stay at the fixed paired triple (42, 43, 44); pop/gen follow the
    suite budget so ``--quick`` reduces Q6 as well.
    """
    kwargs: dict[str, Any] = {}
    if "pop_size" in optimiser_kwargs:
        kwargs["pop_size"] = optimiser_kwargs["pop_size"]
    if "n_gen" in optimiser_kwargs:
        kwargs["n_gen"] = optimiser_kwargs["n_gen"]
    return kwargs


def _print_headlines(results: dict[str, Any]) -> None:
    q1, q2, q3 = results["q1_traceability"], results["q2_conflicts"], results["q3_constraint_satisfaction"]
    q4, q5 = results["q4_benchmark"], results["q5_groundedness"]
    q6 = results.get("q6_ablation")

    def pct(x):
        return "n/a" if x is None else f"{x * 100:.1f}%"

    print("CareLoop evaluation — headline results")
    print(f"  Q1 traceability:          {q1['overall']['traceable']}/{q1['overall']['items']} "
          f"({pct(q1['overall']['rate'])}) [{q1['verdict']}] "
          f"(+{q1['rejected_patients']} REJECTED patients counted separately)")
    print(f"  Q2 conflict resolution:   {q2['cases_passed']}/{q2['cases_total']} cases "
          f"({pct(q2['pass_rate'])}) [{q2['verdict']}]")
    print(f"  Q3 constraint satisfaction: {q3['zero_violation_plans']}/"
          f"{q3['plans_attempted']} zero-violation plans ({pct(q3['zero_violation_rate'])}) "
          f"[{q3['verdict']}] ({q3['infeasible_plans']} infeasible, "
          f"{q3['relaxed_envelopes']} relaxed)")
    print(f"  Q4 optimiser benchmark:   {q4['verdict']} (consumed from "
          f"{q4['artefacts']['csv']}, {q4['artefacts']['main_runs']} main runs)")
    print(f"  Q5 groundedness:          grounded {q5['grounded']['passed']}/{q5['grounded']['total']} "
          f"({pct(q5['grounded']['citation_accuracy'])} citation accuracy), "
          f"escalation {q5['escalation']['passed']}/{q5['escalation']['total']}, "
          f"refusals {q5['irrelevant_refusals']['passed']}/{q5['irrelevant_refusals']['total']} "
          f"[{q5['verdict']}]")
    if q6:
        pooled = q6["selection_ablation"]["pooled"]
        sc = pooled["scalar"].get("mean_worst_day_rel_shortfall_pct")
        adq = pooled["adequacy_first"].get("mean_worst_day_rel_shortfall_pct")
        sc_cost = pooled["scalar"].get("mean_cost") or 0.0
        adq_cost = pooled["adequacy_first"].get("mean_cost") or 0.0
        cost_pct = ((adq_cost / sc_cost - 1.0) * 100.0) if sc_cost else 0.0
        delta = (adq - sc) if (adq is not None and sc is not None) else None
        print(f"  Q6 selection ablation:    adequacy-first worst-day shortfall "
              f"{'n/a' if adq is None else f'{adq:.1f}%'} vs scalar "
              f"{'n/a' if sc is None else f'{sc:.1f}%'} "
              f"(Δ {'n/a' if delta is None else f'{delta:+.1f} pct-pts'}), "
              f"cost {cost_pct:+.1f}% [{q6['verdict']}] "
              f"(composition ablation informational)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluation.run",
        description="CareLoop automated evaluation suite (Q1-Q6).",
    )
    parser.add_argument(
        "--rerun-benchmark", action="store_true",
        help="re-run backend.optim.benchmark (~21s) before consuming its artefacts",
    )
    parser.add_argument(
        "--out-dir", default=str(artifact_dir("evaluation")),
        help="directory for results.json / EVALUATION.md (default: artifacts/evaluation/)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="reduced optimiser budget (pop=20, gen=40) for a fast smoke run",
    )
    args = parser.parse_args(argv)

    optimiser_kwargs = {"pop_size": 20, "n_gen": 40} if args.quick else None
    results = run_suite(rerun_benchmark=args.rerun_benchmark,
                        optimiser_kwargs=optimiser_kwargs)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.json"
    report_path = out_dir / "EVALUATION.md"
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    report_path.write_text(render_report(results), encoding="utf-8")

    _print_headlines(results)
    print(f"\nWrote {results_path}")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
