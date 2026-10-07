"""Harness self-tests: end-to-end on a reduced patient subset, deterministic.

Runs in well under 120s: the expensive pieces (NSGA-II solves) use a small
subset and a reduced budget (pop=20, gen=40); the benchmark artefacts are only
parsed, never re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from evaluation.common import load_patients
from evaluation.q_benchmark import evaluate_q4
from evaluation.q_conflicts import evaluate_q2
from evaluation.q_groundedness import evaluate_q5
from evaluation.q_satisfaction import evaluate_q3
from evaluation.q_traceability import evaluate_q1
from evaluation.report import render_report
from evaluation.run_eval import run_suite

SUBSET_IDS = ["P0001", "P0002", "P0004", "P0006", "P0008", "P0015"]  # incl. 1 REJECTED


def _subset():
    wanted = set(SUBSET_IDS)
    return [p for p in load_patients() if p["patient_id"] in wanted]


# --------------------------------------------------------------------- Q1

def test_q1_traceability_full_is_complete():
    results = evaluate_q1()  # cheap: rule engine only, all 20 patients
    assert results["total_patients"] == 20
    assert results["eligible_patients"] == 18
    assert results["rejected_patient_ids"] == ["P0008", "P0017"]
    assert results["rejected_have_no_targets"] is True
    assert results["overall"]["rate"] == 1.0
    assert results["untraceable_items"] == []
    assert results["verdict"] == "PASS"
    # determinism: same patient -> same rates on a second run
    assert evaluate_q1()["overall"] == results["overall"]


# --------------------------------------------------------------------- Q2

def test_q2_all_conflict_cases_pass():
    results = evaluate_q2()
    assert results["cases_total"] >= 8
    assert results["cases_passed"] == results["cases_total"]
    assert results["checks_passed"] == results["checks_total"]
    assert results["verdict"] == "PASS"
    # spot-check the headline conflict semantics
    by_name = {c["name"]: c for c in results["cases"]}
    c1 = next(v for k, v in by_name.items() if k.startswith("CKD4 + HTN + T2D"))
    sodium = [t for t in c1["engine_targets"]
              if t["nutrient"] == "sodium_mg" and t["kind"] == "max"]
    assert sodium and sodium[0]["value"] == 2000.0
    c2 = next(v for k, v in by_name.items() if k.startswith("CKD3 + HTN with normal K"))
    assert not [t for t in c2["engine_targets"] if t["nutrient"] == "potassium_mg"]


# --------------------------------------------------------------------- Q3

def test_q3_subset_end_to_end():
    results = evaluate_q3(_subset(), pop_size=20, n_gen=40, diagnose_blockers=True)
    attempted = [r for r in results["per_patient"] if r["attempted"]]
    rejected = [r for r in results["per_patient"] if not r["attempted"]]
    assert len(rejected) == 1 and rejected[0]["patient_id"] == "P0008"
    assert len(attempted) == 5

    for row in attempted:
        if row["feasible"]:
            assert row["violation_count"] == 0
            assert row["per_day_totals_compliant"] is True
            assert row["per_day_failures"] == []
        else:
            assert row["violation_count"] >= 1
            assert row["infeasibility_reason"]
            # nothing is served for an infeasible envelope
            assert row.get("blocking_constraints_leave_one_out") is not None

    # every attempted envelope needed (and disclosed) at least the fibre relaxation
    assert all(r["relaxed_constraints"] for r in attempted)
    assert all(
        any(x["nutrient"] == "fiber_g" for x in r["relaxed_constraints"])
        for r in attempted
    )
    # headline consistency
    zero = [r for r in attempted if r["feasible"] and r["violation_count"] == 0]
    assert results["zero_violation_plans"] == len(zero)
    assert results["zero_violation_rate"] == len(zero) / len(attempted)


# --------------------------------------------------------------------- Q4

def test_q4_consumes_benchmark_artefacts_without_rerunning():
    results = evaluate_q4(rerun_benchmark=False)
    assert results["artefacts"]["rerun_benchmark"] is False
    methods = {m["method"] for m in results["headline"]}
    assert methods == {"nsga2", "ga", "greedy", "random"}
    nsga2 = next(m for m in results["headline"] if m["method"] == "nsga2")
    assert nsga2["violation_rate"] == 0.0  # the hard feasibility guarantee
    assert nsga2["runs"] == 20  # 4 envelopes x 5 seeds
    assert len(results["sweep"]) == 9
    assert "pop=80, gen=80" in results["recommendation"]


# --------------------------------------------------------------------- Q5

def test_q5_groundedness_scores():
    results = evaluate_q5()
    assert results["grounded"]["total"] >= 15
    assert results["escalation"]["total"] >= 4
    assert results["irrelevant_refusals"]["total"] >= 3
    assert results["grounded"]["pass_rate"] == 1.0
    assert results["grounded"]["citation_accuracy"] == 1.0
    assert results["escalation"]["pass_rate"] == 1.0
    assert results["irrelevant_refusals"]["pass_rate"] == 1.0
    assert len(results["expert_review_rubric"]) == 5
    assert len(results["known_gaps"]) >= 3


# ------------------------------------------------------------- end-to-end

def test_run_suite_and_report(tmp_path):
    results = run_suite(optimiser_kwargs={"pop_size": 20, "n_gen": 40})
    # full 20-patient suite structure
    assert set(results) == {
        "meta", "q1_traceability", "q2_conflicts",
        "q3_constraint_satisfaction", "q4_benchmark", "q5_groundedness",
    }
    report = render_report(results)
    for section in ("## Q1 — Traceability", "## Q2 — Conflict resolution",
                    "## Q3 — Constraint satisfaction",
                    "## Q4 — Quality/runtime", "## Q5 — Groundedness",
                    "## Limitations"):
        assert section in report
    assert "fibre MIN relaxation" in report or "Fibre MIN relaxation" in report
    assert "newest-first" in report

    # determinism of everything except wall-clock runtimes
    def strip_runtimes(obj):
        if isinstance(obj, dict):
            return {k: strip_runtimes(v) for k, v in obj.items()
                    if k not in ("solver_runtime_s",)}
        if isinstance(obj, list):
            return [strip_runtimes(x) for x in obj]
        return obj

    again = run_suite(optimiser_kwargs={"pop_size": 20, "n_gen": 40})
    assert strip_runtimes(again) == strip_runtimes(results)

    # serialisation is JSON-safe
    json.dumps(results)  # must not raise