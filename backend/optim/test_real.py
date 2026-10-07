"""Tests for the real 190-dish optimiser pipeline (no pytest required).

Run either way::

    .venv/bin/python backend/optim/test_real.py
    pytest backend/optim/test_real.py

Covers:
* the real dish pool loads 190 dishes;
* hand-built envelopes validate against ``shared.envelope_schema``;
* FastEvaluator agrees with the canonical ``problem.evaluate``;
* ``api.run`` returns feasible plans (violation_count == 0) with all contract
  keys and sane runtimes for every test envelope;
* determinism under a fixed seed;
* the feasibility guarantee holds even with a tiny compute budget;
* infeasible pools produce an explicit diagnosis instead of a broken plan.
"""

from __future__ import annotations

import os
import sys
import time

# Allow direct execution: `python backend/optim/test_real.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

from shared.envelope_schema import ConstraintKind, EnvelopeStatus, NutrientConstraint, NutrientKind  # noqa: E402

from backend.optim.api import run  # noqa: E402
from backend.optim.envelopes import build_benchmark_envelopes  # noqa: E402
from backend.optim.problem import (  # noqa: E402
    OBJECTIVE_NAMES,
    allowed_dishes,
    evaluate,
)
from backend.optim.real_data import (  # noqa: E402
    FastEvaluator,
    feasibility_precheck,
    load_dishes,
)

CONTRACT_KEYS = {
    "engine",
    "front_size",
    "violation_count",
    "runtime_ms",
    "objectives",
    "feasible",
    "envelope_id",
    "patient_id",
    "allowed_dish_count",
}

_ENVELOPES = build_benchmark_envelopes()
_DISHES = load_dishes()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_real_pool_loads_190_dishes():
    dishes = load_dishes()
    assert len(dishes) == 190, f"expected 190 dishes, got {len(dishes)}"
    ids = {d.dish_id for d in dishes}
    assert len(ids) == 190, "dish ids are not unique"
    for dish in dishes[:5] + dishes[-5:]:
        assert dish.nutrient("energy_kcal") >= 0
        assert dish.category
        assert isinstance(dish.tags, tuple)


def test_envelopes_validate_against_schema():
    for name, env in _ENVELOPES.items():
        assert env.status == EnvelopeStatus.APPROVED, name
        assert env.envelope_id and env.patient_id
        assert env.targets, name
        for constraint in env.targets:
            assert isinstance(constraint, NutrientConstraint)
            assert constraint.kind in (ConstraintKind.TARGET, ConstraintKind.MIN, ConstraintKind.MAX)
        assert env.is_ready_for_optimisation() is True


def test_all_envelopes_pass_precheck():
    for name, env in _ENVELOPES.items():
        ok, reason = feasibility_precheck(env, _DISHES)
        assert ok, f"{name} precheck failed: {reason}"
        assert len(allowed_dishes(env, _DISHES)) > 0


def test_fast_evaluator_matches_canonical_evaluate():
    env = _ENVELOPES["ckd_strict"]
    ev = FastEvaluator(env, _DISHES)
    rng = np.random.default_rng(7)
    for _trial in range(10):
        idx = rng.integers(0, ev.size, size=ev.slots)
        f, g = ev.eval_indices(idx)
        plan = ev.idx_to_plan(idx)
        objectives, violations = evaluate(plan, env, _DISHES)
        assert np.allclose(
            f, [objectives[k] for k in OBJECTIVE_NAMES], atol=1e-9
        ), (f, objectives)
        # constraint counts must agree exactly (EPS handled identically)
        assert int((g > 0).sum()) == len(violations), (g, violations)


def test_run_feasible_for_all_envelopes():
    for name, env in _ENVELOPES.items():
        t0 = time.perf_counter()
        result = run(env, seed=42)
        elapsed = (time.perf_counter() - t0) * 1000.0
        assert CONTRACT_KEYS.issubset(result.keys()), (name, sorted(result))
        assert result["envelope_id"] == env.envelope_id
        assert result["patient_id"] == env.patient_id
        assert result["feasible"] is True, (name, result.get("violations", [])[:3])
        assert result["violation_count"] == 0, (name, result.get("violations", [])[:3])
        assert result["front_size"] >= 1, name
        assert result["allowed_dish_count"] > 0
        assert set(result["objectives"]) == set(OBJECTIVE_NAMES)
        assert elapsed < 60_000, f"{name}: runtime {elapsed:.0f} ms exceeds 60s"
        assert len(result["plan"]) == 21, name


def test_run_deterministic_under_fixed_seed():
    env = _ENVELOPES["t2d_htn"]
    a = run(env, seed=123, pop_size=20, n_gen=20)
    b = run(env, seed=123, pop_size=20, n_gen=20)
    assert a["plan"] == b["plan"]
    assert a["objectives"] == b["objectives"]
    assert a["engine"] == b["engine"]


def test_run_tiny_budget_still_feasible():
    env = _ENVELOPES["ckd_hyperkalemia"]
    result = run(env, seed=5, pop_size=8, n_gen=4)
    assert result["feasible"] is True
    assert result["violation_count"] == 0
    assert len(result["plan"]) == 21


def test_run_uses_real_dataset_by_default():
    env = _ENVELOPES["t2d_only"]
    result = run(env, seed=42, pop_size=10, n_gen=5)
    # t2d_only excludes only 'dessert' (6 dishes) -> 184 allowed of 190
    assert result["allowed_dish_count"] == 184
    ids = {d for meal in result["plan"] for d in meal}
    real_ids = {d.dish_id for d in _DISHES}
    assert ids <= real_ids, "plan contains dishes outside data/dishes.json"


def test_infeasible_envelope_returns_diagnosis():
    # Sodium MAX of 3 mg/day is provably impossible (min possible day = 15 mg).
    env = _ENVELOPES["ckd_strict"].model_copy(
        update={
            "envelope_id": "env-test-impossible",
            "targets": [
                NutrientConstraint(
                    nutrient=NutrientKind.SODIUM_MG,
                    kind=ConstraintKind.MAX,
                    value=3.0,
                    unit="mg",
                )
            ],
        }
    )
    result = run(env, seed=42)
    assert result["feasible"] is False
    assert result["engine"] == "infeasible"
    assert result.get("infeasibility_reason")
    assert result["plan"] == []  # never a silently broken plan
    assert CONTRACT_KEYS.issubset(result.keys())


def test_exclusions_shrink_pool_as_expected():
    # 'deep_fried' is a tag on 51 dishes; 'coconut milk' an ingredient on 13.
    env = _ENVELOPES["ckd_strict"]
    assert len(allowed_dishes(env, _DISHES)) == 132
    env_hk = _ENVELOPES["ckd_hyperkalemia"]
    assert len(allowed_dishes(env_hk, _DISHES)) == 128


TESTS = [
    test_real_pool_loads_190_dishes,
    test_envelopes_validate_against_schema,
    test_all_envelopes_pass_precheck,
    test_fast_evaluator_matches_canonical_evaluate,
    test_run_feasible_for_all_envelopes,
    test_run_deterministic_under_fixed_seed,
    test_run_tiny_budget_still_feasible,
    test_run_uses_real_dataset_by_default,
    test_infeasible_envelope_returns_diagnosis,
    test_exclusions_shrink_pool_as_expected,
]


def main() -> int:
    print("=" * 74)
    print("CareLoop optimiser — real-data pipeline tests")
    print("=" * 74)
    failures = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    print("-" * 74)
    print(f"{len(TESTS) - failures}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())