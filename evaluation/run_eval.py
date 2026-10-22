from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.datasets.paths import dataset_path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge.runtime import selected_release, source_hashes
from evaluation.ablation import evaluate_ablation
from evaluation.benchmark import evaluate_benchmark
from evaluation.common import ROOT, load_patients
from evaluation.conflicts import evaluate_conflicts
from evaluation.external import evaluate_external
from evaluation.groundedness import evaluate_groundedness
from evaluation.report import render_report
from evaluation.satisfaction import evaluate_satisfaction
from evaluation.traceability import evaluate_traceability

__all__ = ["main", "run_suite"]


def _run_vcs(command: list[str]) -> str | None:
    import subprocess

    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _source_revision() -> str:
    """Missing VCS metadata must not discard computed evaluation results."""
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
    ext_pop = min(20, optimiser_kwargs.get("pop_size", 20))
    ext_gen = min(40, optimiser_kwargs.get("n_gen", 40))
    external = evaluate_external(
        kb=kb,
        max_nhanes_subjects=max_nhanes_subjects,
        plan_pop_size=ext_pop,
        plan_n_gen=ext_gen,
    )

    import hashlib
    import platform

    revision = _source_revision()
    release = selected_release()
    source_paths = sorted(p for directory in ("backend", "shared", "rules", "evaluation")
                          for p in (ROOT / directory).rglob("*.py"))
    code_hash = hashlib.sha256()
    for path in source_paths:
        code_hash.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())

    empirical_verdict = (
        "PASS"
        if all(x["verdict"] == "PASS" for x in (benchmark, ablation, external))
        else "FAIL"
    )
    contracts_verdict = (
        "PASS"
        if all(x["verdict"] == "PASS" for x in (traceability, conflicts, satisfaction, groundedness))
        else "FAIL"
    )

    return {
        "meta": {
            "suite": "CareLoop empirical & external evaluation v3 (real-world cohorts, mathematical bounds & clinical benchmarks)",
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
                "empirical_and_external": {
                    "criteria": ["external", "benchmark", "ablation"],
                    "verdict": empirical_verdict,
                },
                "regression_contracts": {
                    "criteria": ["traceability", "conflicts", "constraint_satisfaction", "groundedness"],
                    "verdict": contracts_verdict,
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

    print("CareLoop evaluation — empirical & external headline results")
    if external and external.get("nhanes_cohort", {}).get("available"):
        nh = external["nhanes_cohort"]
        adh = nh["dietary_recall_adherence"]
        pa = nh.get("plan_adequacy_stress_test") or {}
        mm = external["mimic_longitudinal_trends"]
        pf = mm.get("prefix_forecast_benchmark", {}).get("combined", {})
        nm = (
            mm.get("noisy_regime_and_mining_benchmark", {})
            .get("noisy_trend_estimators", {})
            .get("estimators", [])
        )
        ts_est = next((e for e in nm if e["estimator"] == "theil-sen"), {})
        hb = external["healthbench_chat"]
        em_bin = hb.get("emergency_triage_binary_metrics") or {}
        top = hb.get("topical_scope_discrimination") or {}
        ret = hb.get("retrieval_benchmark") or {}
        print(f"  NHANES clinical cohort:   {nh['evaluated_subjects']} subjects stratified; "
              f"24h recall hard-MAX exceedance {pct(adh['baseline_hard_violation_day_rate'])} "
              f"({adh['recalled_days_with_hard_max_violation']}/{adh['recalled_days_evaluated']} days); "
              f"weight-stratified 7d plan all-MIN adequacy "
              f"{pa.get('plans_meeting_all_min_floors')}/{pa.get('hard_feasible_plans')} "
              f"({pct(pa.get('all_min_floors_met_rate'))}, mean worst-day MIN shortfall "
              f"{pa.get('mean_worst_day_min_shortfall_pct')}%)")
        print(f"  MIMIC-IV & trend mining:  rolling 3-obs prefix forecast recall "
              f"{pct(pf.get('sensitivity_recall'))} ({pf.get('tp')}/{pf.get('positive_crossings')}), "
              f"specificity {pct(pf.get('specificity'))}, PPV {pct(pf.get('precision_ppv'))}; "
              f"noisy regime (σ=0.05) Theil-Sen TP {pct(ts_est.get('tp_detection_rate'))}, "
              f"plateau FP {pct(ts_est.get('plateau_fp_rate'))}, overall FP {pct(ts_est.get('overall_fp_rate'))}")
        print(f"  HealthBench & retrieval:  emergent triage recall {pct(em_bin.get('escalation_sensitivity_recall'))} "
              f"(specificity {pct(em_bin.get('non_emergent_specificity'))}, F1 {em_bin.get('f1_score')}); "
              f"topical precision {pct(top.get('topical_precision_among_answered'))} "
              f"(non-dietary clinical rejection {pct(top.get('non_dietary_rejection_specificity'))}, "
              f"condition-matched guideline rate {pct(top.get('condition_matched_guideline_rate'))}); "
              f"held-out retrieval Hit@1 {pct(ret.get('production_hit_at_1'))}, "
              f"MRR {ret.get('production_mrr')}, e2e citation accuracy {pct(ret.get('production_e2e_citation_accuracy'))}")
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
        comp_2d = (ablation["composition_ablation"]["pooled"].get("two_dish") or {}).get("adequacy_first", {})
        print(f"  Selection & composition:  1-dish adequacy-first worst-day shortfall "
              f"{'n/a' if adq is None else f'{adq:.1f}%'} vs scalar "
              f"{'n/a' if sc is None else f'{sc:.1f}%'} "
              f"(Δ {'n/a' if delta is None else f'{delta:+.1f} pct-pts'}, cost {cost_pct:+.1f}%); "
              f"2-dish worst-day shortfall {comp_2d.get('mean_worst_day_rel_shortfall_pct', 0.0):.1f}% "
              f"[{ablation['verdict']}]")
    adq_sum = satisfaction.get("adequacy_summary") or {}
    print(f"  Fixture adequacy & gates: 7d all-MIN-floors met {adq_sum.get('plans_meeting_all_min_floors')}/"
          f"{satisfaction['zero_violation_plans']} ({pct(adq_sum.get('all_min_floors_met_rate'))}, "
          f"mean worst-day MIN shortfall {adq_sum.get('mean_worst_day_min_shortfall_pct')}%); "
          f"regression contracts: traceability {traceability['verdict']}, "
          f"conflicts {conflicts['verdict']}, hard-MAX {satisfaction['verdict']}, "
          f"groundedness {groundedness['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluation.run",
        description="CareLoop two-tier evaluation suite.",
    )
    parser.add_argument(
        "--rerun-benchmark", action="store_true",
        help="re-run backend.optim.benchmark (~21s) before consuming its artefacts",
    )
    parser.add_argument(
        "--out-dir",
        help="explicitly export results.json and EVALUATION.md to this external directory",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="reduced optimiser/NHANES budget (pop=20, gen=40) for a fast smoke run",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir is not None else None
    if out_dir is not None and (out_dir == ROOT or ROOT in out_dir.parents):
        raise ValueError("Evaluation output directory must be outside the code checkout")

    optimiser_kwargs = {"pop_size": 20, "n_gen": 40} if args.quick else None
    max_nhanes = 200 if args.quick else 600
    results = run_suite(
        rerun_benchmark=args.rerun_benchmark,
        optimiser_kwargs=optimiser_kwargs,
        max_nhanes_subjects=max_nhanes,
    )

    _print_headlines(results)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        results_path = out_dir / "results.json"
        report_path = out_dir / "EVALUATION.md"
        results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        report_path.write_text(render_report(results), encoding="utf-8")
        print(f"\nWrote {results_path}")
        print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
