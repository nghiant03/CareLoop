from __future__ import annotations

import math
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from itertools import combinations_with_replacement as _combinations

from backend.optim.envelopes import build_benchmark_envelopes
from backend.optim.exact_reference import (
    one_day_exact,
    plan_vs_exact,
    prove_infeasible,
)
from backend.optim.problem import (
    EPS,
    MEALS_PER_DAY,
    OBJECTIVE_NAMES,
    SCALAR_WEIGHTS,
    TAG_PREFERENCE,
    allowed_dishes,
    evaluate,
)
from backend.optim.real_data import load_dishes
from backend.optim.solver import solve
from backend.optim.toy_data import NUTRIENT_KEYS, Dish
from shared.envelope_schema import (
    CitationSource,
    ConstraintKind,
    EnvelopeStatus,
    ExclusionFlag,
    ExclusionKind,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


def _dish(did: str, energy: float, protein: float, sodium: float, price: float) -> Dish:
    return Dish(
        dish_id=did,
        name=did,
        category="test",
        nutrients={
            "energy_kcal": energy,
            "protein_g": protein,
            "sodium_mg": sodium,
        },
        tags=("pool",),
        price_sgd=price,
    )


TINY_POOL: list[Dish] = [
    _dish("alpha_a", 500, 20, 300, 3.0),
    _dish("bravo_b", 600, 30, 500, 4.0),
    _dish("charlie_c", 400, 10, 200, 2.0),
    _dish("delta_d", 550, 25, 400, 3.5),
    _dish("echo_e", 450, 15, 250, 2.5),
]


def _envelope(targets: list[NutrientConstraint], exclusions: list[ExclusionFlag] | None = None):
    return NutrientEnvelope(
        envelope_id="env-exact-test",
        patient_id="p-exact",
        status=EnvelopeStatus.APPROVED,
        version=1,
        patient_snapshot=PatientSummary(
            patient_id="p-exact", age=50, sex="F", weight_kg=60, diagnoses=[]
        ),
        targets=targets,
        exclusions=exclusions or [],
        priority_basis="test",
    )


def _cite() -> CitationSource:
    return CitationSource(guideline="test", section="1", rule_id="R-TEST")


def _feasible_envelope():
    return _envelope(
        [
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1500.0, unit="kcal"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=45.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1100.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MAX, value=80.0, unit="g"),
        ]
    )


def _impossible_envelope():
    return _envelope(
        [
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100.0, unit="mg"),
        ]
    )


def _empty_pool_envelope():
    return _envelope(
        [
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=5000.0, unit="mg"),
        ],
        exclusions=[
            ExclusionFlag(
                kind=ExclusionKind.DIET_PATTERN,
                value="pool",
                reason="test: exclude everything",
                citation=_cite(),
            )
        ],
    )


def _one_day_dev(totals: dict[str, float], env) -> float:
    dev = 0.0
    for c in env.targets:
        value = totals[c.nutrient.value]
        if c.kind == ConstraintKind.TARGET:
            dev += abs(value - c.value)
        elif c.kind == ConstraintKind.MIN:
            dev += max(0.0, c.value - value)
        else:
            dev += max(0.0, value - c.value)
    return dev


def _brute_force(env, pool: list[Dish], n_slots: int = 3):
    lookup_size = len({d.dish_id for d in pool})
    denom = math.log(lookup_size) if lookup_size > 1 else 1.0
    data: dict[str, list[float]] = {
        "nutrient_target_deviation": [],
        "preference_sum": [],
        "cost": [],
        "best_scalar": [],
    }
    tuples: list[tuple[str, ...]] = []
    for combo in _combinations(range(len(pool)), n_slots):
        dishes = [pool[i] for i in combo]
        totals = {k: sum(d.nutrient(k) for d in dishes) for k in NUTRIENT_KEYS}
        if any(
            totals[c.nutrient.value] > c.value + EPS
            for c in env.targets
            if c.kind == ConstraintKind.MAX
        ):
            continue
        dev = _one_day_dev(totals, env)
        pref = sum(sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in dishes)
        cost = sum(d.price_sgd for d in dishes)
        counts: dict[str, int] = {}
        for d in dishes:
            counts[d.dish_id] = counts.get(d.dish_id, 0) + 1
        probs = [c / n_slots for c in counts.values()]
        entropy = -sum(p * math.log(p) for p in probs)
        norm_entropy = min(1.0, entropy / denom) if denom > 0 else 0.0
        variety = -(0.5 * norm_entropy + 0.5 * len(counts) / min(lookup_size, n_slots))
        scalar = sum(
            SCALAR_WEIGHTS[k] * v
            for k, v in zip(
                OBJECTIVE_NAMES,
                [dev, -pref / n_slots, variety, cost],
            )
        )
        data["nutrient_target_deviation"].append(dev)
        data["preference_sum"].append(pref)
        data["cost"].append(cost)
        data["best_scalar"].append(scalar)
        tuples.append(tuple(sorted(d.dish_id for d in dishes)))

    def pick(key: str):
        if not data["nutrient_target_deviation"]:
            return None
        values = data[key]
        best_value = min(values)
        tol = 1e-9 * max(1.0, abs(best_value))
        cands = sorted(
            (t, v) for v, t in zip(values, tuples) if v <= best_value + tol
        )
        return cands[0]

    return len(tuples), pick


def _assert_matches_bruteforce(env, pool: list[Dish], n_slots: int = 3):
    count, pick = _brute_force(env, pool, n_slots=n_slots)
    exact = one_day_exact(env, pool, n_slots=n_slots)
    assert exact["feasible_day"] == (count > 0)
    assert exact["feasible_combo_count"] == count
    for key, bkey in (
        ("nutrient_target_deviation", "nutrient_target_deviation"),
        ("preference_sum", "preference_sum"),
        ("cost", "cost"),
        ("best_scalar", "best_scalar"),
    ):
        expected = pick(key)
        actual = exact["best_scalar"] if key == "best_scalar" else exact["best"][bkey]
        if expected is None:
            assert actual["dish_ids"] == [] and actual["value"] is None
            continue
        ids, value = expected
        assert list(ids) == actual["dish_ids"], (key, ids, actual)
        assert abs(value - actual["value"]) < 1e-6, (key, value, actual)
    return exact


def test_one_day_exact_matches_bruteforce_on_tiny_pool():
    env = _feasible_envelope()
    pool = sorted(allowed_dishes(env, TINY_POOL), key=lambda d: d.dish_id)
    exact = _assert_matches_bruteforce(env, pool)
    assert exact["feasible_day"] is True
    assert exact["feasible_combo_count"] > 0
    assert exact["pool_size"] == len(pool)
    assert exact["n_slots"] == MEALS_PER_DAY
    cheapest = min(d.price_sgd for d in pool)
    assert abs(exact["best"]["cost"]["value"] - 3 * cheapest) < 1e-9


def test_one_day_exact_generic_n_slots_matches_bruteforce():
    env = _feasible_envelope()
    pool = sorted(allowed_dishes(env, TINY_POOL), key=lambda d: d.dish_id)
    _assert_matches_bruteforce(env, pool, n_slots=2)


def test_one_day_exact_is_deterministic():
    env = _feasible_envelope()
    a = one_day_exact(env, TINY_POOL)
    b = one_day_exact(env, TINY_POOL)
    assert a == b


def test_infeasible_max_proves_infeasible():
    env = _impossible_envelope()
    assert prove_infeasible(env, TINY_POOL) is True
    exact = one_day_exact(env, TINY_POOL)
    assert exact["feasible_day"] is False
    assert exact["feasible_combo_count"] == 0
    assert exact["best"]["cost"]["value"] is None
    assert exact["best"]["cost"]["dish_ids"] == []


def test_empty_pool_proves_infeasible():
    env = _empty_pool_envelope()
    assert allowed_dishes(env, TINY_POOL) == []
    assert prove_infeasible(env, TINY_POOL) is True


def test_solver_diagnosis_reports_proven_infeasible():
    for env in (_impossible_envelope(), _empty_pool_envelope()):
        result = solve(env, TINY_POOL, seed=1, pop_size=8, n_gen=4)
        assert result["feasible"] is False
        assert result["engine"] == "infeasible"
        assert result["plan"] == []
        assert result["infeasibility_status"] == "proven_infeasible"
        assert result["exact_reference"]["feasible_day"] is False
        assert result["exact_reference"]["feasible_combo_count"] == 0


def test_solver_feasible_result_shape_unchanged():
    env = _feasible_envelope()
    result = solve(env, TINY_POOL, seed=1, pop_size=10, n_gen=10)
    assert result["feasible"] is True
    assert result["violation_count"] == 0
    assert len(result["plan"]) == 7 * MEALS_PER_DAY
    assert set(result["objectives"]) == set(OBJECTIVE_NAMES)
    assert "infeasibility_status" not in result
    assert "exact_reference" not in result
    assert result.get("infeasibility_reason") is None


def test_plan_vs_exact_gaps_nonnegative_and_variety_excluded():
    env = _feasible_envelope()
    exact = one_day_exact(env, TINY_POOL)
    best_cost_day = exact["best"]["cost"]["dish_ids"]
    day = [[dish_id] for dish_id in best_cost_day]
    plan = day * 7
    _, violations = evaluate(plan, env, TINY_POOL)
    assert not violations

    report = plan_vs_exact(env, TINY_POOL, plan)
    assert report["n_days"] == 7
    assert report["exact"]["feasible_day"] is True
    assert report["excluded_objectives"] == ["variety"]
    assert "variety" not in report["objectives"]
    for name in ("nutrient_target_deviation", "preference_sum", "cost"):
        entry = report["objectives"][name]
        assert entry["gaps"] is not None
        assert all(g >= -1e-9 for g in entry["gaps"]), (name, entry)
        assert entry["mean_gap"] >= -1e-9
        assert abs(entry["seven_day_lower_bound"] - 7.0 * entry["exact_one_day_best"]) < 1e-9
    cost_entry = report["objectives"]["cost"]
    assert all(abs(g) < 1e-9 for g in cost_entry["gaps"])
    assert "all four objectives" in report["disclosure"]


def test_plan_vs_exact_rejects_malformed_plan():
    env = _feasible_envelope()
    try:
        plan_vs_exact(env, TINY_POOL, [["alpha_a"]] * 4)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for a plan length %% MEALS_PER_DAY != 0")


def test_real_data_performance_smoke():
    dishes = load_dishes()
    env = build_benchmark_envelopes()["ckd_strict"]
    t0 = time.perf_counter()
    exact = one_day_exact(env, dishes)
    elapsed = time.perf_counter() - t0
    assert exact["feasible_day"] is True
    assert exact["feasible_combo_count"] > 0
    assert elapsed < 2.0, f"one_day_exact took {elapsed:.2f}s on the real pool"


def test_solver_continues_when_precheck_falsely_fails(monkeypatch):
    import numpy as np

    import backend.optim.solver as solver_mod

    env = _feasible_envelope()

    def fake_precheck(envelope, dishes, n_days=7):
        return False, "artificial precheck failure"

    monkeypatch.setattr(solver_mod, "feasibility_precheck", fake_precheck)
    monkeypatch.setattr(solver_mod, "HAS_PYMOO", True)
    monkeypatch.setattr(
        solver_mod,
        "_pymoo_front",
        lambda ev, seed, pop, gen, method="nsga2": [np.zeros(21, dtype=int) + 2],
    )
    result = solver_mod.solve(env, TINY_POOL, seed=1, pop_size=8, n_gen=4)
    assert result["feasible"] is True, result.get("infeasibility_reason")
    assert "infeasibility_status" not in result


def test_solver_reports_search_exhausted_when_heuristics_fail(monkeypatch):
    import numpy as np

    import backend.optim.solver as solver_mod

    env = _feasible_envelope()

    monkeypatch.setattr(solver_mod, "HAS_PYMOO", True)
    monkeypatch.setattr(
        solver_mod,
        "_pymoo_front",
        lambda ev, seed, pop, gen, method="nsga2": [np.ones(21, dtype=int)],
    )
    monkeypatch.setattr(solver_mod, "repair_plan", lambda ev, idx, seed=0: None)
    monkeypatch.setattr(solver_mod, "greedy_feasible_plan", lambda ev, seed=0: None)

    result = solver_mod.solve(env, TINY_POOL, seed=1, pop_size=8, n_gen=4)
    assert result["feasible"] is False
    assert result["infeasibility_status"] == "search_exhausted"
    assert result["exact_reference"]["feasible_day"] is True
    assert result["exact_reference"]["feasible_combo_count"] > 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run .venv/bin/python -m pytest backend/optim/test_exact.py")
