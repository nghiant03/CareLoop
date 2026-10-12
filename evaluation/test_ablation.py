"""Tests for evaluation/q_ablation.py (Q6) — pure-function tests + one smoke run.

The real-data test uses a small patient subset
with heavily reduced optimiser / GA budgets; everything else runs on stub
dishes and hand-checkable numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

from backend.optim.problem import OBJECTIVE_NAMES, evaluate, is_feasible
from backend.optim.toy_data import Dish
from evaluation.q_ablation import (
    CompositionEvaluator,
    _repair_individual,
    adequacy_rows,
    composition_ga,
    derive_selection_verdict,
    evaluate_q6,
    plan_metrics,
)
from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


# ---------------------------------------------------------------------------
# Stub data: a small pool with hand-checkable numbers
# ---------------------------------------------------------------------------
def _dish(did: str, energy: float, protein: float, sodium: float, potassium: float,
          price: float, category: str, tags: tuple) -> Dish:
    return Dish(
        dish_id=did,
        name=did,
        category=category,
        nutrients={
            "energy_kcal": energy, "protein_g": protein, "sodium_mg": sodium,
            "potassium_mg": potassium,
        },
        tags=tags,
        price_sgd=price,
    )


ABLATION_POOL: list[Dish] = [
    _dish("m_protein", 600, 30, 400, 500, 8.0, "hawker", ("lean_protein",)),
    _dish("m_rice", 700, 10, 900, 300, 2.0, "cai_png", ("moderate_sodium",)),
    _dish("m_veg", 400, 8, 200, 800, 3.0, "soup", ("vegetable", "high_fiber")),
    _dish("m_healthy", 500, 20, 100, 100, 4.0, "healthy", ("high_fiber",)),
    _dish("s_soup", 200, 5, 100, 200, 1.5, "soup", ("vegetable",)),
    _dish("s_veg", 300, 2, 50, 50, 1.0, "healthy", ("vegetable", "high_fiber")),
    _dish("s_salty", 450, 6, 700, 400, 2.5, "cai_png", ("high_sodium",)),
    _dish("d_cake", 300, 3, 150, 100, 2.0, "dessert", ("high_energy",)),
]


def _envelope() -> NutrientEnvelope:
    return NutrientEnvelope(
        envelope_id="env-ablation-test",
        patient_id="p-ablation",
        status=EnvelopeStatus.APPROVED,
        version=1,
        patient_snapshot=PatientSummary(
            patient_id="p-ablation", age=50, sex="F", weight_kg=60, diagnoses=[]
        ),
        targets=[
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG,
                               kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.POTASSIUM_MG,
                               kind=ConstraintKind.MAX, value=2500.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G,
                               kind=ConstraintKind.MIN, value=50.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL,
                               kind=ConstraintKind.TARGET, value=1800.0, unit="kcal"),
        ],
        exclusions=[],
        priority_basis="test",
    )


def _totals(*days: dict[str, float]) -> list[dict[str, float]]:
    return list(days)


# ---------------------------------------------------------------- adequacy
def test_adequacy_rows_mirrors_plan_service_semantics():
    env = _envelope()
    daily = _totals(
        {"energy_kcal": 1800.0, "protein_g": 60.0, "sodium_mg": 1500.0, "potassium_mg": 1000.0},
        {"energy_kcal": 1400.0, "protein_g": 30.0, "sodium_mg": 1000.0, "potassium_mg": 900.0},
    )
    rows = {r["nutrient"]: r for r in adequacy_rows(daily, env)}
    # MAX ceilings are excluded from adequacy
    assert set(rows) == {"protein_g", "energy_kcal"}
    protein = rows["protein_g"]  # MIN 50: worst day 30 -> shortfall 20, 40%
    assert protein["aim"] == 50.0
    assert protein["mean_daily_shortfall"] == pytest.approx(10.0)  # (0 + 20) / 2
    assert protein["worst_day_rel_shortfall_pct"] == pytest.approx(40.0)
    assert protein["met_days_fraction"] == pytest.approx(0.5)
    energy = rows["energy_kcal"]  # TARGET 1800: worst (lowest) day 1400 -> 22.2%
    assert energy["mean_daily_shortfall"] == pytest.approx(200.0)  # (0 + 400) / 2
    assert energy["worst_day_rel_shortfall_pct"] == pytest.approx(400.0 / 18.0, rel=1e-6)
    assert energy["met_days_fraction"] == pytest.approx(0.5)

    # dimensionless per-aim gap: mean over days of gap/aim (percent), so
    # cross-aim pooling never mixes kcal/g/mg units
    assert protein["mean_daily_rel_shortfall_pct"] == pytest.approx(20.0)  # mean(0, 40)
    assert energy["mean_daily_rel_shortfall_pct"] == pytest.approx(
        (0.0 + 400.0 / 18.0) / 2, rel=1e-6
    )

    # zero-aim guard: relative shortfall is 0 when aim <= 0
    zero_env = _envelope().model_copy(update={"targets": [
        NutrientConstraint(nutrient=NutrientKind.PROTEIN_G,
                           kind=ConstraintKind.MIN, value=0.0, unit="g"),
    ]})
    rows0 = adequacy_rows(daily, zero_env)
    assert rows0[0]["worst_day_rel_shortfall_pct"] == 0.0
    assert rows0[0]["mean_daily_rel_shortfall_pct"] == 0.0


def test_plan_metrics_matches_problem_evaluate():
    env = _envelope()
    # 2-dish-per-slot plan (multi-dish meals are natively supported):
    # per day 3 x (30 + 2) = 96 g protein (MIN 50 met), 3 x (600 + 300) = 2700
    # kcal (TARGET 1800 overshot by 900), sodium 3 x (400 + 50) = 1350 <= 2000.
    plan = [["m_protein", "s_veg"]] * 21
    metrics = plan_metrics(plan, env, ABLATION_POOL)
    objectives, violations = evaluate(plan, env, ABLATION_POOL)
    assert metrics["hard_feasible"] is (not violations)
    assert metrics["violation_count"] == len(violations)
    assert metrics["cost"] == pytest.approx(objectives["cost"])
    assert metrics["variety"] == pytest.approx(objectives["variety"])
    assert metrics["scalar_score"] == pytest.approx(
        sum(w * objectives[k] for k, w in {
            "nutrient_target_deviation": 0.001, "preference_fit": 0.5,
            "variety": 0.5, "cost": 0.02}.items())
    )
    assert len(metrics["adequacy"]) == 2  # protein MIN + energy TARGET only
    protein = next(r for r in metrics["adequacy"] if r["nutrient"] == "protein_g")
    assert protein["mean_daily_shortfall"] == pytest.approx(0.0)
    assert protein["worst_day_rel_shortfall_pct"] == 0.0
    assert protein["met_days_fraction"] == 1.0
    energy = next(r for r in metrics["adequacy"] if r["nutrient"] == "energy_kcal")
    assert energy["met_days_fraction"] == 0.0
    assert energy["worst_day_rel_shortfall_pct"] == pytest.approx(50.0)

    # a hard-infeasible plan with a real protein shortfall:
    # protein 3 x (10 + 5) = 45 (short 5/day, 10%), sodium 3 x (900 + 100) = 3000
    # violates the 2000 mg MAX ceiling.
    bad = [["m_rice", "s_soup"]] * 21
    bad_metrics = plan_metrics(bad, env, ABLATION_POOL)
    _objs, bad_violations = evaluate(bad, env, ABLATION_POOL)
    assert bad_violations and bad_metrics["hard_feasible"] is False
    protein = next(r for r in bad_metrics["adequacy"] if r["nutrient"] == "protein_g")
    assert protein["mean_daily_shortfall"] == pytest.approx(5.0)
    assert protein["worst_day_rel_shortfall_pct"] == pytest.approx(10.0)
    assert protein["met_days_fraction"] == 0.0


def test_plan_metrics_pools_dimensionless_gaps_only():
    """The pooled plan-level gap must be dimensionless, never a raw unit mix.

    Regression for the pooled ``mean_daily_shortfall`` average that mixed
    kcal/g/mg across aims: plan_metrics now pools only the per-aim relative
    gap, while unit-bearing per-aim gaps stay inside ``adequacy`` rows.
    """
    env = _envelope()
    plan = [["m_protein", "s_veg"]] * 21
    metrics = plan_metrics(plan, env, ABLATION_POOL)
    assert "mean_daily_shortfall" not in metrics  # raw pooled mix removed
    # protein MIN 50: met every day (96 g/day) -> 0%; energy TARGET 1800:
    # 2700 every day -> 50% every day. Pooled mean over the two aims:
    assert metrics["mean_daily_rel_shortfall_pct"] == pytest.approx(25.0)
    # unit-bearing per-aim gaps are retained per aim, not pooled:
    energy = next(r for r in metrics["adequacy"] if r["nutrient"] == "energy_kcal")
    assert energy["mean_daily_shortfall"] == pytest.approx(900.0)


# ---------------------------------------------------------------- repair
def _no_day_duplicates(ev: CompositionEvaluator, ind: np.ndarray) -> bool:
    plan = ev.to_plan(ind)
    for day in range(7):
        ids = [d for slot in plan[day * 3:(day + 1) * 3] for d in slot]
        if len(ids) != len(set(ids)):
            return False
    return True


def test_repair_individual_fixes_day_duplicates():
    """Repetition repair must stack per slot/role and make real progress.

    Regression (finding 38): the duplicate branch concatenated 1-D gid arrays
    on axis 1 (AxisError on every repetition-bearing individual) and could
    re-select the duplicated dish itself, livelocking until max_iters.
    """
    env = _envelope()
    ev = CompositionEvaluator(env, ABLATION_POOL)
    main_pos = {d.dish_id: i for i, d in enumerate(ev.main_pool)}
    side_pos = {d.dish_id: i for i, d in enumerate(ev.side_pool)}

    # every day repeats (m_protein, s_veg) x3 but satisfies both MAX
    # ceilings, so only the repetition limit is violated. The old code
    # raised AxisError before any repair; it must now converge.
    ind = np.zeros((ev.slots, 2), dtype=int)
    ind[:, 0] = main_pos["m_protein"]
    ind[:, 1] = side_pos["s_veg"]
    _F, G, rep = ev.eval_single(ind)
    assert rep and (G <= 0).all()
    fixed = _repair_individual(ev, ind, max_iters=100)
    assert fixed is not None, "repetition repair livelocked or failed"
    assert ev.is_feasible_individual(fixed)
    assert _no_day_duplicates(ev, fixed)

    # livelock variant: the duplicated main is the lowest-MAX-contribution
    # candidate in its own pool (m_healthy: sodium 100 + potassium 100), so
    # a replacement allowed to equal the duplicate never makes progress.
    ind2 = np.zeros((ev.slots, 2), dtype=int)
    ind2[:, 0] = main_pos["m_healthy"]
    ind2[:, 1] = side_pos["s_veg"]
    _F2, G2, rep2 = ev.eval_single(ind2)
    assert rep2 and (G2 <= 0).all()
    fixed2 = _repair_individual(ev, ind2, max_iters=100)
    assert fixed2 is not None, "duplicate was re-selected instead of replaced"
    assert ev.is_feasible_individual(fixed2)
    assert _no_day_duplicates(ev, fixed2)


def test_repair_individual_selects_a_duplicate_bearing_day():
    """The most-violated day may be repetition-free; duplicates elsewhere.

    Regression (finding 38): with day 0 the most MAX-violated day but
    repetition-free, a naive fix of the AxisError would look for duplicates
    on day 0 and crash on the empty bincount result instead of selecting a
    duplicate-bearing day.
    """
    env = _envelope()
    ev = CompositionEvaluator(env, ABLATION_POOL)
    main_pos = {d.dish_id: i for i, d in enumerate(ev.main_pool)}
    side_pos = {d.dish_id: i for i, d in enumerate(ev.side_pool)}

    # day 0: six distinct dishes, sodium 400+900+200+100+50+700 = 2350 >
    # 2000 (the only MAX violation, on the most-violated day, no duplicate);
    # days 1-6: MAX-compliant but repeat (m_protein, s_veg) x3.
    ind = np.zeros((ev.slots, 2), dtype=int)
    day0_mains = ["m_protein", "m_rice", "m_veg"]
    day0_sides = ["s_soup", "s_veg", "s_salty"]
    for slot in range(3):
        ind[0 * 3 + slot, 0] = main_pos[day0_mains[slot]]
        ind[0 * 3 + slot, 1] = side_pos[day0_sides[slot]]
    for day in range(1, 7):
        for slot in range(3):
            ind[day * 3 + slot, 0] = main_pos["m_protein"]
            ind[day * 3 + slot, 1] = side_pos["s_veg"]
    _F, G, rep = ev.eval_single(ind)
    assert rep and (G > 0).any()
    fixed = _repair_individual(ev, ind, max_iters=200)
    assert fixed is not None, "repair failed on mixed repetition/MAX violation"
    assert ev.is_feasible_individual(fixed)
    assert _no_day_duplicates(ev, fixed)


def test_repair_individual_fixes_max_violation_by_dish_replacement():
    """MAX repair addresses six dish positions, subtracting ONE dish.

    Regression (finding 39): the replacement search indexed three meal rows
    with six dish positions (IndexError for any position >= 3) and earlier
    positions subtracted the combined main+side meal instead of the single
    dish being replaced. Tested directly, independent of greedy success.
    """
    env = _envelope()
    ev = CompositionEvaluator(env, ABLATION_POOL)
    main_pos = {d.dish_id: i for i, d in enumerate(ev.main_pool)}
    side_pos = {d.dish_id: i for i, d in enumerate(ev.side_pool)}

    # day 0: six distinct dishes (no repetition anywhere), sodium 2350 > the
    # 2000 mg ceiling; days 1-6: repetition-free and compliant
    # (mains m_healthy/m_veg/m_protein, sides s_veg/s_soup/s_salty ->
    # sodium 1550, potassium 2050).
    ind = np.zeros((ev.slots, 2), dtype=int)
    day0_mains = ["m_protein", "m_rice", "m_veg"]
    day0_sides = ["s_soup", "s_veg", "s_salty"]
    ok_mains = ["m_healthy", "m_veg", "m_protein"]
    ok_sides = ["s_veg", "s_soup", "s_salty"]
    for slot in range(3):
        ind[0 * 3 + slot, 0] = main_pos[day0_mains[slot]]
        ind[0 * 3 + slot, 1] = side_pos[day0_sides[slot]]
    for day in range(1, 7):
        for slot in range(3):
            ind[day * 3 + slot, 0] = main_pos[ok_mains[slot]]
            ind[day * 3 + slot, 1] = side_pos[ok_sides[slot]]
    _F, G, rep = ev.eval_single(ind)
    assert not rep and (G > 0).any()  # pure MAX violation to repair

    fixed = _repair_individual(ev, ind, max_iters=200)
    assert fixed is not None, "MAX repair did not converge"
    assert ev.is_feasible_individual(fixed)
    # only dishes on day 0 changed; every other day is untouched
    for day in range(1, 7):
        assert np.array_equal(ind[day * 3:(day + 1) * 3],
                              fixed[day * 3:(day + 1) * 3])


# ------------------------------------------------------------------ verdict
def test_derive_selection_verdict_crafted_numbers():
    def pooled(sc_worst, adq_worst, sc_cost, adq_cost, feas=1.0):
        return {
            "scalar": {"rows": 5, "feasibility_rate": 1.0,
                       "mean_worst_day_rel_shortfall_pct": sc_worst,
                       "mean_cost": sc_cost},
            "adequacy_first": {"rows": 5, "feasibility_rate": feas,
                               "mean_worst_day_rel_shortfall_pct": adq_worst,
                               "mean_cost": adq_cost},
        }

    verdict, note = derive_selection_verdict(pooled(50.0, 40.0, 100.0, 105.0))
    assert verdict == "PASS" and note is None

    # not strictly reduced -> FAIL naming the condition
    verdict, note = derive_selection_verdict(pooled(50.0, 50.0, 100.0, 105.0))
    assert verdict == "FAIL" and note is not None and "not strictly reduced" in note

    # cost increase > 10% -> FAIL
    verdict, note = derive_selection_verdict(pooled(50.0, 40.0, 100.0, 115.0))
    assert verdict == "FAIL" and note is not None and "cost" in note

    # feasibility below 100% -> FAIL
    verdict, note = derive_selection_verdict(pooled(50.0, 40.0, 100.0, 105.0, feas=0.8))
    assert verdict == "FAIL" and note is not None and "feasibility" in note

    # no comparable rows -> FAIL
    verdict, note = derive_selection_verdict({})
    assert verdict == "FAIL" and note is not None and "no comparable" in note


# ------------------------------------------- composition evaluator cross-check
def test_composition_evaluator_cross_check_against_problem_evaluate():
    env = _envelope()
    ev = CompositionEvaluator(env, ABLATION_POOL)
    # MAIN = allowed minus drink/dessert/kopitiam; SIDE = soup/healthy/cai_png
    # or the vegetable tag — both non-empty on the stub pool.
    assert ev.size_m > 0 and ev.size_s > 0
    main_ids = {d.dish_id for d in ev.main_pool}
    side_ids = {d.dish_id for d in ev.side_pool}
    assert "d_cake" not in main_ids and "d_cake" not in side_ids
    assert "m_protein" in main_ids and "s_soup" in side_ids

    rng = np.random.default_rng(0)
    checked = 0
    for _trial in range(24):
        ind = np.zeros((21, 2), dtype=int)
        ind[:, 0] = rng.integers(0, ev.size_m, 21)
        ind[:, 1] = rng.integers(0, ev.size_s, 21)
        plan = ev.to_plan(ind)
        objectives, violations = evaluate(plan, env, ABLATION_POOL)
        F, G, _rep = ev.eval_single(ind)
        assert np.allclose(F, [objectives[k] for k in OBJECTIVE_NAMES], atol=1e-9)
        problem_max = sorted(v["amount"] for v in violations
                             if v["type"].startswith("max"))
        my_over = sorted((G[G > 0] + 1e-9).tolist())
        assert len(problem_max) == len(my_over)
        if problem_max:
            assert np.allclose(problem_max, my_over, atol=1e-9)
        checked += 1
    assert checked == 24

    # repetition limit: a dish served as main AND side on the same day is
    # flagged by the composition evaluator; problem.evaluate has no such rule
    shared = main_ids & side_ids
    assert shared, "expected MAIN/SIDE overlap to exercise the repetition check"
    did = min(shared)
    mi = [d.dish_id for d in ev.main_pool].index(did)
    si = [d.dish_id for d in ev.side_pool].index(did)
    ind = np.zeros((21, 2), dtype=int)
    ind[:, 0], ind[:, 1] = mi, si
    _F, _G, rep = ev.eval_single(ind)
    assert rep is True
    # and a repetition-free plan is not flagged
    ind2 = np.zeros((21, 2), dtype=int)
    ind2[:, 0] = 0
    ind2[:, 1] = [i % ev.size_s for i in range(21)]
    _F2, _G2, rep2 = ev.eval_single(ind2)
    manual_dup = any(
        len({
            ev.main_pool[ind2[d * 3 + s, 0]].dish_id
            for s in range(3)
        } | {
            ev.side_pool[ind2[d * 3 + s, 1]].dish_id
            for s in range(3)
        }) < 6
        for d in range(7)
    )
    assert rep2 == manual_dup


def test_composition_ga_keeps_a_feasible_front():
    env = _envelope()
    ev = CompositionEvaluator(env, ABLATION_POOL)
    ga = composition_ga(ev, seed=42, pop_size=12, n_gen=8, repair_iters=100)
    assert ga["front"], f"GA lost feasibility: {ga['note']}"
    for entry in ga["front"]:
        assert entry["feasible"] is True
        assert is_feasible(entry["plan"], env, ABLATION_POOL)
        # role eligibility + per-day repetition limit hold
        for slot in entry["plan"]:
            main, side = slot
            assert main in {d.dish_id for d in ev.main_pool}
            assert side in {d.dish_id for d in ev.side_pool}
        for day in range(7):
            ids = [d for slot in entry["plan"][day * 3:(day + 1) * 3] for d in slot]
            assert len(ids) == len(set(ids)), "dish repeated within a day"
    # front entries are directly consumable by the selection strategies
    from evaluation.q_ablation import _STRATEGIES

    for selector in _STRATEGIES.values():
        picked = selector(ga["front"], env, ABLATION_POOL)
        assert picked["feasible"] is True


# ------------------------------------------------------------- real-data smoke
def test_q6_smoke_real_data_two_patients():
    from backend.optim.real_data import load_dishes
    from evaluation.common import load_patients

    patients = load_patients()
    dishes = load_dishes()
    subset = patients[:3]  # includes at least one eligible patient
    results = evaluate_q6(
        subset, dishes, seeds=(42,), pop_size=12, n_gen=12,
        composition_patients=1, composition_pop=16, composition_gen=10,
    )
    assert set(results) == {
        "question", "definition", "selection_ablation",
        "composition_ablation", "exact_reference", "verdict", "verdict_note",
    }
    assert results["verdict"] in ("PASS", "FAIL")

    sel = results["selection_ablation"]
    assert set(sel["pooled"]) == {"scalar", "normalised", "adequacy_first"}
    for name, pooled in sel["pooled"].items():
        assert isinstance(pooled["rows"], int)
        for field in ("mean_worst_day_rel_shortfall_pct", "mean_cost",
                      "mean_met_days_fraction", "feasibility_rate"):
            value = pooled[field]
            assert value is None or isinstance(value, (int, float))
    assert sel["pooled"]["scalar"]["rows"] >= 1
    assert sel["per_patient"] and sel["per_patient"][0]["patient_id"]
    for name in ("normalised", "adequacy_first"):
        d = sel["paired_deltas"][name]
        assert d["rows"] == sel["pooled"]["scalar"]["rows"]

    comp = results["composition_ablation"]
    assert set(comp["pooled"]) == {"one_dish", "two_dish"}
    assert comp["pools"]["main_pool_size"] > 0 and comp["pools"]["side_pool_size"] > 0
    assert "UNVERIFIED" in comp["note"] and "doubles dishes per day" in comp["note"]

    exact = results["exact_reference"]
    for name in ("nutrient_target_deviation", "preference_sum", "cost"):
        entry = exact["aggregate"][name]
        assert entry["plans_with_reference"] >= 1
        assert entry["mean_gap"] is None or entry["mean_gap"] >= 0.0
        assert entry["patients_at_per_day_optimum"] <= entry["plans_with_reference"]
    assert "NOT an optimum for all four objectives" in exact["disclosure"]
    assert "variety" in exact["excluded_objectives"][0]
