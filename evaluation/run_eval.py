"""Evaluation orchestrator: runs Tier-1 contract checks and Tier-2 benchmarks/external studies.

All generated outputs (``results.json`` and ``EVALUATION.md``) are written
outside the code checkout under ``artifact_dir("evaluation")`` (default
``CARELOOP_DATASET_DIR/outputs/evaluation/``, override ``CARELOOP_ARTIFACT_DIR``).
Never write reports or raw data inside the repository.

Usage::

    .venv/bin/python -m evaluation.run            # full two-tier suite
    .venv/bin/python -m evaluation.run --quick    # reduced optimiser/NHANES budget
    .venv/bin/python -m evaluation.run --rerun-benchmark
"""

from __future__ import annotations
from backend.datasets.paths import dataset_path

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.common import ROOT, load_patients
from evaluation.ablation import evaluate_ablation
from evaluation.benchmark import evaluate_benchmark
from evaluation.conflicts import evaluate_conflicts
from evaluation.external import evaluate_external
from evaluation.groundedness import evaluate_groundedness
from evaluation.satisfaction import evaluate_satisfaction
from evaluation.traceability import evaluate_traceability
from evaluation.report import render_report
from backend.storage_paths import artifact_dir
from backend.knowledge.runtime import selected_release, source_hashes

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
    the suite — that would discard every already-computed criterion result.
    """
    revision = _run_vcs(
        ["jj", "--ignore-working-copy", "log", "-r", "@",
         "--no-graph", "-T", "commit_id"]
    )
    if revision is None:
        revision = _run_vcs(["git", "rev-parse", "HEAD"])
    return revision or "unavailable (no accessible VCS revision)"


def run_suite(
    rerun_benchmark: bool = False,
    optimiser_kwargs: dict[str, Any] | None = None,
    max_nhanes_subjects: int | None = 600,
) -> dict[str, Any]:
    """Run Tier-1 contract gates and Tier-2 empirical/external evaluations."""
    from backend.optim.real_data import load_dishes

    optimiser_kwargs = optimiser_kwargs or {}
    patients = load_patients()

    traceability = evaluate_traceability(patients)
    conflicts = evaluate_conflicts()

    dishes = load_dishes()
    satisfaction = evaluate_satisfaction(patients, dishes=dishes, **optimiser_kwargs)

    benchmark = evaluate_benchmark(rerun_benchmark=rerun_benchmark)

    from backend.app.core.kb_loader import get_kb
    kb = get_kb()
    groundedness = evaluate_groundedness(kb)

    ablation = evaluate_ablation(patients, dishes=dishes, **ablation_kwargs(optimiser_kwargs))
    external = evaluate_external(kb=kb, max_nhanes_subjects=max_nhanes_subjects)

    import hashlib
    import platform

    revision = _source_revision()
    release = selected_release()
    source_paths = sorted(p for directory in ("backend", "shared", "rules", "evaluation")
                          for p in (ROOT / directory).rglob("*.py"))
    code_hash = hashlib.sha256()
    for path in source_paths:
        code_hash.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())

    tier1_verdict = (
        "PASS"
        if all(x["verdict"] == "PASS" for x in (traceability, conflicts, satisfaction, groundedness))
        else "FAIL"
    )
    tier2_verdict = (
        "PASS"
        if all(x["verdict"] == "PASS" for x in (benchmark, ablation, external))
        else "FAIL"
    )

    return {
        "meta": {
            "suite": "CareLoop two-tier evaluation v2 (contract verification + external empirical benchmarks)",
            "seed": optimiser_kwargs.get("seed", 42),
            "pop_size": optimiser_kwargs.get("pop_size", 40),
            "n_gen": optimiser_kwargs.get("n_gen", 80),
            "patients": len(patients),
            "dishes": len(dishes),
            "source_revision": revision,
            "working_code_sha256": code_hash.hexdigest(),
            "knowledge_release_id": release.release_id if release else None,
            "data_hashes": {**source_hashes(), "data/patients.json": hashlib.sha256(dataset_path("patients.json").read_bytes()).hexdigest()},
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "tiers": {
                "tier1_contracts": {
                    "criteria": ["traceability", "conflicts", "constraint_satisfaction", "groundedness"],
                    "verdict": tier1_verdict,
                },
                "tier2_empirical_and_external": {
                    "criteria": ["benchmark", "ablation", "external"],
                    "verdict": tier2_verdict,
                },
            },
        },
        "traceability": traceability,
        "conflicts": conflicts,
        "constraint_satisfaction": satisfaction,
        "benchmark": benchmark,
        "groundedness": groundedness,
        "ablation": ablation,
        "external": external,
    }


def ablation_kwargs(optimiser_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Map the shared optimiser budget onto the ablation evaluation parameters.

    Seeds stay at the fixed paired triple (42, 43, 44); pop/gen follow the
    suite budget so ``--quick`` reduces the ablation run as well.
    """
    kwargs: dict[str, Any] = {}
    if "pop_size" in optimiser_kwargs:
        kwargs["pop_size"] = optimiser_kwargs["pop_size"]
    if "n_gen" in optimiser_kwargs:
        kwargs["n_gen"] = optimiser_kwargs["n_gen"]
    return kwargs


def _print_headlines(results: dict[str, Any]) -> None:
    traceability = results["traceability"]
    conflicts = results["conflicts"]
    satisfaction = results["constraint_satisfaction"]
    benchmark = results["benchmark"]
    groundedness = results["groundedness"]
    ablation = results.get("ablation")
    external = results.get("external")

    def pct(x):
        return "n/a" if x is None else f"{x * 100:.1f}%"

    print("CareLoop evaluation — headline results")
    print("  [Tier 1 — Deterministic contract & safety gates]")
    print(f"  Traceability:             {traceability['overall']['traceable']}/{traceability['overall']['items']} "
          f"({pct(traceability['overall']['rate'])}) [{traceability['verdict']}] "
          f"(+{traceability['rejected_patients']} REJECTED patients counted separately)")
    print(f"  Conflict resolution:      {conflicts['cases_passed']}/{conflicts['cases_total']} cases "
          f"({pct(conflicts['pass_rate'])}) [{conflicts['verdict']}]")
    print(f"  Constraint satisfaction:  {satisfaction['zero_violation_plans']}/"
          f"{satisfaction['plans_attempted']} zero-violation plans ({pct(satisfaction['zero_violation_rate'])}) "
          f"[{satisfaction['verdict']}] ({satisfaction['infeasible_plans']} infeasible, "
          f"{satisfaction['relaxed_envelopes']} relaxed)")
    print(f"  Groundedness:             grounded {groundedness['grounded']['passed']}/{groundedness['grounded']['total']} "
          f"({pct(groundedness['grounded']['citation_accuracy'])} citation accuracy), "
          f"escalation {groundedness['escalation']['passed']}/{groundedness['escalation']['total']}, "
          f"refusals {groundedness['irrelevant_refusals']['passed']}/{groundedness['irrelevant_refusals']['total']} "
          f"[{groundedness['verdict']}]")
    print("  [Tier 2 — Empirical benchmarks & external dataset evaluations]")
    print(f"  Optimiser benchmark:      {benchmark['verdict']} (consumed from "
          f"{benchmark['artefacts']['csv']}, {benchmark['artefacts']['main_runs']} main runs)")
    if ablation:
        pooled = ablation["selection_ablation"]["pooled"]
        sc = pooled["scalar"].get("mean_worst_day_rel_shortfall_pct")
        adq = pooled["adequacy_first"].get("mean_worst_day_rel_shortfall_pct")
        sc_cost = pooled["scalar"].get("mean_cost") or 0.0
        adq_cost = pooled["adequacy_first"].get("mean_cost") or 0.0
        cost_pct = ((adq_cost / sc_cost - 1.0) * 100.0) if sc_cost else 0.0
        delta = (adq - sc) if (adq is not None and sc is not None) else None
        print(f"  Selection ablation:       adequacy-first worst-day shortfall "
              f"{'n/a' if adq is None else f'{adq:.1f}%'} vs scalar "
              f"{'n/a' if sc is None else f'{sc:.1f}%'} "
              f"(Δ {'n/a' if delta is None else f'{delta:+.1f} pct-pts'}), "
              f"cost {cost_pct:+.1f}% [{ablation['verdict']}] "
              f"(composition ablation informational)")
    if external and external.get("nhanes_cohort", {}).get("available"):
        nh = external["nhanes_cohort"]
        mm = external["mimic_longitudinal_trends"]
        hb = external["healthbench_chat"]
        print(f"  External datasets:        NHANES {nh['traceability']['traceable']}/{nh['traceability']['items']} "
              f"traceable across {nh['evaluated_subjects']} subjects, "
              f"recall hard-violation rate {pct(nh['dietary_recall_adherence']['baseline_hard_violation_day_rate'])}; "
              f"MIMIC {mm['real_trajectory_flags']['total']} flags ({mm['patients_total']} pts); "
              f"HealthBench {hb['nutrition_queries']['answered']}/{hb['nutrition_queries']['total']} nutrition queries "
              f"grounded [{external['verdict']}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluation.run",
        description="CareLoop two-tier evaluation suite (external output only).",
    )
    parser.add_argument(
        "--rerun-benchmark", action="store_true",
        help="re-run backend.optim.benchmark (~21s) before consuming its artefacts",
    )
    parser.add_argument(
        "--out-dir", default=str(artifact_dir("evaluation")),
        help="external directory for results.json / EVALUATION.md (default: CARELOOP_DATASET_DIR/outputs/evaluation/)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="reduced optimiser/NHANES budget (pop=20, gen=40) for a fast smoke run",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir == ROOT or ROOT in out_dir.parents:
        raise ValueError("Evaluation output directory must be outside the code checkout")

    optimiser_kwargs = {"pop_size": 20, "n_gen": 40} if args.quick else None
    max_nhanes = 200 if args.quick else 600
    results = run_suite(
        rerun_benchmark=args.rerun_benchmark,
        optimiser_kwargs=optimiser_kwargs,
        max_nhanes_subjects=max_nhanes,
    )

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
