"""Harness self-tests: end-to-end on a reduced patient subset, deterministic.

NSGA-II solves use a small patient subset and reduced budget (pop=20, gen=40);
runtime depends on the environment. The benchmark artefacts are only
parsed, never re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from evaluation.benchmark import evaluate_benchmark
from evaluation.common import load_patients, target_supported
from evaluation.conflicts import evaluate_conflicts
from evaluation.external import evaluate_external
from evaluation.groundedness import evaluate_groundedness
from evaluation.report import render_report
from evaluation.run_eval import run_suite
from evaluation.satisfaction import evaluate_satisfaction
from evaluation.traceability import evaluate_traceability

SUBSET_IDS = ["P0001", "P0002", "P0004", "P0006", "P0008", "P0015"]  # incl. 1 REJECTED


def _subset():
    wanted = set(SUBSET_IDS)
    return [p for p in load_patients() if p["patient_id"] in wanted]


# Traceability

def test_traceability_full_is_complete():
    results = evaluate_traceability()  # cheap: rule engine only, all 20 patients
    assert results["total_patients"] == 20
    # P0007/P0016 (stage-5 pre-dialysis vocabulary) are scope-rejected by
    # the rules engine; P0008/P0017 were already out of scope.
    assert results["eligible_patients"] == 16
    assert results["rejected_patient_ids"] == ["P0007", "P0008", "P0016", "P0017"]
    assert results["rejected_have_no_targets"] is True
    assert results["overall"]["rate"] == 1.0
    assert results["untraceable_items"] == []
    assert results["verdict"] == "PASS"
    # determinism: same patient -> same rates on a second run
    assert evaluate_traceability()["overall"] == results["overall"]


def test_traceability_definition_describes_the_matching_policy_honestly():
    """Traceability credits matching cited values, even in superseded rows; it is not provenance."""
    results = evaluate_traceability()
    assert "superseded losers never get credited" not in results["definition"]
    assert "weaker than provenance" in results["definition"]
    # pin the actual policy: a SUPERSEDED row with a matching final value
    # and complete citation still credits the target
    target = {"nutrient": "sodium_mg", "kind": "max", "value": 2000.0}
    trace = [
        {"rule_id": "R-A",
         "action_summary": "set sodium_mg max = 2000 mg/d [SUPERSEDED by R-B]",
         "citation": {"rule_id": "R-A", "guideline": "G", "section": "S"}},
        {"rule_id": "R-B",
         "action_summary": "set sodium_mg max = 1800 mg/d",
         "citation": {"rule_id": "R-B", "guideline": "G", "section": "S"}},
    ]
    assert target_supported(target, trace) is True
    assert target_supported(
        {"nutrient": "sodium_mg", "kind": "max", "value": 1500.0}, trace
    ) is False


# Conflict resolution

def test_all_conflict_cases_pass():
    results = evaluate_conflicts()
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


# Constraint satisfaction

def test_constraint_satisfaction_subset_end_to_end():
    results = evaluate_satisfaction(_subset(), pop_size=20, n_gen=40, diagnose_blockers=True)
    attempted = [r for r in results["per_patient"] if r["attempted"]]
    rejected = [r for r in results["per_patient"] if not r["attempted"]]
    assert len(rejected) == 1 and rejected[0]["patient_id"] == "P0008"
    assert len(attempted) == 5

    # New encoding (hard = MAX ceilings + exclusions): every attempted
    # envelope must solve to a zero-violation plan whose per-day totals
    # satisfy every hard MAX ceiling of the solved envelope.
    for row in attempted:
        assert row["feasible"] is True, row
        assert row["violation_count"] == 0
        assert row["per_day_hard_compliant"] is True
        assert row["per_day_hard_failures"] == []
        assert row["days_checked"] == 7
        # MIN floors / TARGETs are soft: reported informationally, never as
        # violations. Keys carry nutrient AND kind identity so a nutrient
        # with both a MIN floor and a TARGET keeps both entries.
        for aim_key, aim in row["soft_aims_by_constraint"].items():
            assert aim["kind"] in ("min", "target")
            assert aim_key.endswith(":" + aim["kind"]), aim_key

    # P0001's envelope has BOTH fiber MIN 25 and TARGET 30: both summaries
    # must survive instead of one overwriting the other
    p0001 = next(r for r in attempted if r["patient_id"] == "P0001")
    assert "fiber_g:min" in p0001["soft_aims_by_constraint"]
    assert "fiber_g:target" in p0001["soft_aims_by_constraint"]

    # Production composition evaluates original aims without relaxing floors.
    assert all(r["meal_complete"] for r in attempted)
    assert all(not r["relaxed_constraints"] for r in attempted)
    # headline consistency
    zero = [r for r in attempted if r["feasible"] and r["violation_count"] == 0]
    assert results["zero_violation_plans"] == len(zero)
    assert results["zero_violation_rate"] == len(zero) / len(attempted)
    assert results["verdict"] == "PASS"


# Daily gap semantics

def _pd_dishes():
    from backend.optim.toy_data import Dish

    return [
        Dish(dish_id="lo", name="lo", category="hawker",
             nutrients={"energy_kcal": 500.0, "fiber_g": 9.0, "sodium_mg": 100.0},
             tags=(), price_sgd=1.0),
        Dish(dish_id="hi", name="hi", category="hawker",
             nutrients={"energy_kcal": 700.0, "fiber_g": 12.0, "sodium_mg": 200.0},
             tags=(), price_sgd=1.0),
    ]


def _pd_envelope(targets):
    from shared.envelope_schema import (
        EnvelopeStatus,
        NutrientEnvelope,
        PatientSummary,
    )

    return NutrientEnvelope(
        envelope_id="env-per-day-test", patient_id="p-per-day",
        status=EnvelopeStatus.APPROVED, version=1,
        patient_snapshot=PatientSummary(
            patient_id="p-per-day", age=50, sex="F", weight_kg=60, diagnoses=[]
        ),
        targets=targets, exclusions=[], priority_basis="test",
    )


def _pd_targets(min_floor, fiber_target=30.0, energy_target=1800.0, sodium_max=700.0):
    from shared.envelope_schema import ConstraintKind, NutrientConstraint, NutrientKind

    return [
        NutrientConstraint(nutrient=NutrientKind.SODIUM_MG,
                           kind=ConstraintKind.MAX, value=sodium_max, unit="mg"),
        NutrientConstraint(nutrient=NutrientKind.FIBER_G,
                           kind=ConstraintKind.MIN, value=min_floor, unit="g"),
        NutrientConstraint(nutrient=NutrientKind.FIBER_G,
                           kind=ConstraintKind.TARGET, value=fiber_target, unit="g"),
        NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL,
                           kind=ConstraintKind.TARGET, value=energy_target, unit="kcal"),
    ]


def test_per_day_check_preserves_aim_identity_and_daily_gap_aggregation():
    """Keep both MIN/TARGET summaries and prevent opposite-day gaps cancelling."""
    from evaluation.satisfaction import _per_day_check

    dishes = _pd_dishes()
    plan = ([["lo"]] * 3 + [["hi"]] * 3) * 3 + [["lo"]] * 3  # lo,hi,lo,hi,lo,hi,lo
    solved = _pd_envelope(_pd_targets(min_floor=25.0))
    check = _per_day_check(plan, solved, dishes)

    # identity: fiber MIN 25 and TARGET 30 both survive
    assert set(check["soft_aims_by_constraint"]) == {
        "fiber_g:min", "fiber_g:target", "energy_kcal:target",
    }
    # daily gaps are aggregated before averaging: |1500-1800| and
    # |2100-1800| both equal 300 -> mean distance 300, never 0
    energy = check["soft_aims_by_constraint"]["energy_kcal:target"]
    assert energy["mean_distance"] == 300.0
    # fiber TARGET 30: distances 3 (lo days, 27 g) and 6 (hi days, 36 g)
    assert check["soft_aims_by_constraint"]["fiber_g:target"]["mean_distance"] == round(
        (3.0 * 4 + 6.0 * 3) / 7, 3
    )
    # MIN summary stays worst-day: min day total 27 g >= floor 25 -> no shortfall
    assert check["soft_aims_by_constraint"]["fiber_g:min"]["worst_day_shortfall"] == 0.0
    assert check["soft_aims"]["fiber_g"] == check["soft_aims_by_constraint"]["fiber_g:target"]
    # hard MAX verification against the solved envelope
    assert check["hard_compliant"] is True and check["hard_failures"] == []


def test_per_day_check_retains_original_aims_when_floors_are_relaxed():
    """Relaxed fallback floors must not rewrite the reported aim."""
    from evaluation.satisfaction import _per_day_check

    dishes = _pd_dishes()
    plan = [["lo"]] * 21  # every day: 27 g fiber, 1500 kcal, 300 mg sodium
    solved = _pd_envelope(_pd_targets(min_floor=20.0))  # relaxed fallback floor
    original = _pd_envelope(_pd_targets(min_floor=25.0))  # approved aim

    default = _per_day_check(plan, solved, dishes)
    assert default["soft_aims_by_constraint"]["fiber_g:min"]["floor"] == 20.0  # solved aims

    with_original = _per_day_check(plan, solved, dishes, aims_envelope=original)
    fiber = with_original["soft_aims_by_constraint"]["fiber_g:min"]
    # adequacy is assessed against the ORIGINAL approved floor: 27 g against
    # 25 g is a 0 g shortfall, but against the relaxed 20 g floor it would
    # also be 0 — use a plan below the original floor to expose the aim:
    assert fiber["floor"] == 25.0


def test_per_day_check_original_aims_expose_real_shortfall():
    """A plan meeting only the relaxed floor still shows the original gap."""
    from evaluation.satisfaction import _per_day_check

    dishes = _pd_dishes()
    # Delivery is 27 g/day: the relaxed 20 g floor is met, but the original
    # 30 g floor retains a 3 g shortfall.
    plan = [["lo"]] * 21
    solved = _pd_envelope(_pd_targets(min_floor=20.0))
    original = _pd_envelope(_pd_targets(min_floor=30.0, fiber_target=40.0))
    with_original = _per_day_check(plan, solved, dishes, aims_envelope=original)
    fiber = with_original["soft_aims_by_constraint"]["fiber_g:min"]
    assert fiber["floor"] == 30.0
    assert fiber["worst_day_total"] == 27.0
    assert fiber["worst_day_shortfall"] == 3.0
    relaxed_view = _per_day_check(plan, solved, dishes)
    assert relaxed_view["soft_aims_by_constraint"]["fiber_g:min"]["floor"] == 20.0
    assert relaxed_view["soft_aims_by_constraint"]["fiber_g:min"]["worst_day_shortfall"] == 0.0


def test_benchmark_consumes_artefacts_without_rerunning():
    results = evaluate_benchmark(rerun_benchmark=False)
    assert results["artefacts"]["rerun_benchmark"] is False
    methods = {m["method"] for m in results["headline"]}
    # every method recorded in the CSV artefact, not a hardcoded subset
    assert methods == {"nsga2", "nsga2-raw", "nsga3", "nsga3-raw", "moead",
                       "moead-raw", "age", "age-raw", "sms", "sms-raw",
                       "ga", "greedy", "random"}
    nsga2 = next(m for m in results["headline"] if m["method"] == "nsga2")
    assert nsga2["violation_rate"] == 0.0  # the hard feasibility guarantee
    assert nsga2["runs"] == 20  # 4 envelopes x 5 seeds
    # the verdict note names the data-derived HV winner, not a fixed method
    best = max(results["headline"], key=lambda m: m["mean_hv"])
    assert best["method"] in results["verdict_note"]
    assert len(results["sweep"]) == 9
    assert "pop=80, gen=80" in results["recommendation"]


# Groundedness

def test_groundedness_scores():
    results = evaluate_groundedness()
    assert results["grounded"]["total"] >= 15
    assert results["escalation"]["total"] >= 4
    assert results["irrelevant_refusals"]["total"] >= 3
    assert results["grounded"]["pass_rate"] == 1.0
    assert results["grounded"]["citation_accuracy"] == 1.0
    assert results["escalation"]["pass_rate"] == 1.0
    assert results["irrelevant_refusals"]["pass_rate"] == 1.0
    assert len(results["expert_review_rubric"]) == 5
    assert len(results["known_gaps"]) >= 3


# External datasets

def test_external_datasets():
    results = evaluate_external(max_nhanes_subjects=200, plan_pop_size=12, plan_n_gen=16)
    assert results["verdict"] == "PASS"
    nhanes = results["nhanes_cohort"]
    assert nhanes["available"] is True
    assert nhanes["evaluated_subjects"] > 100
    assert nhanes["engine_errors"] == 0
    recall = nhanes["dietary_recall_adherence"]
    assert recall["recalled_days_evaluated"] > 50
    assert 0.5 < recall["baseline_hard_violation_day_rate"] < 1.0
    plan_adq = nhanes["plan_adequacy_stress_test"]
    assert plan_adq["subjects_evaluated"] == 20
    assert 0.0 < plan_adq["all_min_floors_met_rate"] < 1.0
    assert plan_adq["mean_worst_day_min_shortfall_pct"] > 0.0

    mimic = results["mimic_longitudinal_trends"]
    assert mimic["available"] is True
    assert mimic["patients_total"] == 100
    pf = mimic["prefix_forecast_benchmark"]["combined"]
    assert pf["episodes"] > 100
    assert 0.0 < pf["sensitivity_recall"] < 1.0
    assert 0.0 < pf["specificity"] < 1.0
    assert 0.0 < pf["precision_ppv"] < 1.0
    noisy = mimic["noisy_regime_and_mining_benchmark"]["noisy_trend_estimators"]["estimators"]
    ts_row = next(e for e in noisy if e["estimator"] == "theil-sen")
    assert 0.0 < ts_row["overall_fp_rate"] < 1.0

    hb = results["healthbench_chat"]
    assert hb["available"] is True
    assert hb["total_corpus_conversations"] > 3000
    em_bin = hb["emergency_triage_binary_metrics"]
    assert 0.0 < em_bin["escalation_sensitivity_recall"] < 1.0
    assert 0.0 < em_bin["non_emergent_specificity"] < 1.0
    top = hb["topical_scope_discrimination"]
    assert 0.0 < top["topical_precision_among_answered"] < 1.0
    assert 0.0 < top["non_dietary_rejection_specificity"] < 1.0
    assert 0.0 < top["condition_matched_guideline_rate"] < 1.0
    ret = hb["retrieval_benchmark"]
    assert ret["queries_total"] == 58
    assert 0.0 < ret["production_hit_at_1"] < 1.0
    assert 0.0 < ret["production_mrr"] < 1.0

    # Independent external ground-truth & mathematical oracle evaluations
    gt = results["guideline_extraction_ground_truth"]
    assert gt["available"] is True
    assert gt["society_polarity_concordance_rate"] == 1.0
    assert gt["fda_interaction_concordance_rate"] == 1.0

    milp_cat = results["milp_and_sgfoodid_catalogue"]
    assert milp_cat["milp_global_optimum_oracle"]["max_abs_discrepancy_vs_exact"] == 0.0
    assert milp_cat["sgfoodid_external_catalogue"]["total_rows"] == 2689
    assert milp_cat["sgfoodid_external_catalogue"]["complete_10_nutrient_rows"] >= 527

    eicu = results["eicu_multi_center_trends"]
    assert eicu["available"] is True
    assert eicu["icu_stays_total"] > 2000
    assert eicu["prefix_forecast_benchmark"]["combined"]["episodes"] > 1000

    uci = results["uci_external_cohorts"]
    assert uci["uci_ckd"]["available"] is True
    assert uci["uci_ckd"]["evaluated_subjects"] == 400
    assert uci["uci_ckd"]["external_physician_label_clustering"]["adjusted_rand_index"] > 0.3


# End-to-end evaluation

def test_run_suite_and_report(tmp_path):
    results = run_suite(optimiser_kwargs={"pop_size": 20, "n_gen": 40})
    # full 20-patient suite + external datasets structure
    assert set(results) == {
        "meta", "traceability", "conflicts",
        "constraint_satisfaction", "benchmark", "groundedness",
        "ablation", "external",
    }
    report = render_report(results)
    for section in ("## Traceability", "## Conflict resolution",
                    "## Constraint satisfaction",
                    "## Quality/runtime", "## Groundedness",
                    "## Objective/selection & meal-composition ablation",
                    "## External dataset evaluation",
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

