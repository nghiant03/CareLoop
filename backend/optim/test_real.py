"""Tests for the real-dish optimiser pipeline (no pytest required).

Run either way::

    .venv/bin/python backend/optim/test_real.py
    pytest backend/optim/test_real.py

Covers:
* the real dish pool loads 214 dishes (190 manual + 24 curated renal
  replenishment dishes);
* hand-built envelopes validate against ``shared.envelope_schema``;
* FastEvaluator agrees with the canonical ``problem.evaluate``;
* ``api.run`` returns feasible plans (violation_count == 0) with all contract
  keys and sane runtimes for every test envelope;
* determinism under a fixed seed;
* the feasibility guarantee holds even with a tiny compute budget;
* infeasible pools produce an explicit diagnosis instead of a broken plan;
* the benchmark comparison methods (nsga3 / moead / age / sms) stay feasible,
  finite and deterministic through ``solve()``, the raw mode reports the
  untouched front, and ``api.run`` keeps the NSGA-II + guarantee default;
* benchmark artifact regeneration works (smoke-mode subprocess run).
"""

from __future__ import annotations

import csv
import math
import os
import subprocess
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
from backend.optim.solver import solve  # noqa: E402

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
DISH_COUNT = 214  # 190 manual_curation + 24 curated_renal_replenishment


def test_real_pool_loads_214_dishes():
    dishes = load_dishes()
    assert len(dishes) == DISH_COUNT, f"expected {DISH_COUNT} dishes, got {len(dishes)}"
    ids = {d.dish_id for d in dishes}
    assert len(ids) == DISH_COUNT, "dish ids are not unique"
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
    # t2d_only excludes only 'dessert' (7 dishes) -> 207 allowed of 214
    assert result["allowed_dish_count"] == 207
    ids = {d for meal in result["plan"] for d in meal}
    real_ids = {d.dish_id for d in _DISHES}
    assert ids <= real_ids, "plan contains dishes outside data/dishes.json"


def test_infeasible_envelope_returns_diagnosis():
    # Sodium MAX of 0 mg/day is provably impossible (the lowest-sodium dish in
    # the pool carries 1 mg — the curated banana — so the least possible day
    # is 3 mg > 0).
    env = _ENVELOPES["ckd_strict"].model_copy(
        update={
            "envelope_id": "env-test-impossible",
            "targets": [
                NutrientConstraint(
                    nutrient=NutrientKind.SODIUM_MG,
                    kind=ConstraintKind.MAX,
                    value=0.0,
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
    # 'deep_fried' is a tag on 51 dishes; 'coconut milk' an ingredient on 13
    # (58 distinct dishes excluded of the 214-dish pool; none of the 24
    # curated renal-replenishment dishes is deep-fried or coconut-milk based).
    env = _ENVELOPES["ckd_strict"]
    assert len(allowed_dishes(env, _DISHES)) == 156
    env_hk = _ENVELOPES["ckd_hyperkalemia"]
    # additionally excludes the 'high_potassium' tag (6 original dishes; the
    # curated K-rich fruit dishes sit below the 700 mg tag threshold and are
    # caught by the rulebook semantic threshold instead)
    assert len(allowed_dishes(env_hk, _DISHES)) == 152


def test_semantic_exclusion_mapping_filters_real_pool():
    """Rulebook semantic exclusions must match their intended catalogue predicates."""
    from shared.envelope_schema import ExclusionFlag, ExclusionKind

    from backend.optim.envelopes import ckd_strict

    def pool_with_single_exclusion(kind: ExclusionKind, value: str) -> int:
        base = ckd_strict()
        env = base.model_copy(
            update={
                "envelope_id": "env-test-semantic",
                "exclusions": [
                    ExclusionFlag(
                        kind=kind,
                        value=value,
                        reason="test",
                        citation=base.exclusions[0].citation,
                    )
                ],
            }
        )
        return len(allowed_dishes(env, _DISHES))

    total = len(_DISHES)
    cat, diet = ExclusionKind.DISH_CATEGORY, ExclusionKind.DIET_PATTERN
    # Documented semantic thresholds must bite on the real pool's tails.
    assert pool_with_single_exclusion(cat, "high_potassium_foods") < total - 20, (
        "semantic K threshold must exclude the high-K tail"
    )
    assert pool_with_single_exclusion(cat, "phosphate_additive_processed") < total - 5
    assert pool_with_single_exclusion(cat, "sugar_sweetened_beverage") < total - 10
    assert pool_with_single_exclusion(diet, "high_glycaemic_load") < total - 10
    # Unknown values keep literal-only behaviour (no accidental matches).
    assert pool_with_single_exclusion(cat, "nonexistent_category_xyz") == total


# ---------------------------------------------------------------------------
# Benchmark algorithm-comparison tests (nsga3 / moead / age / sms)
# ---------------------------------------------------------------------------
NEW_METHODS = ("nsga3", "moead", "age", "sms")
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))


def test_new_algorithms_guaranteed_feasible_and_finite():
    """Every comparison method through solve() stays feasible with finite objectives."""
    env = _ENVELOPES["t2d_only"]
    for method in NEW_METHODS:
        result = solve(env, _DISHES, seed=11, pop_size=40, n_gen=10, method=method)
        assert result["feasible"] is True, (method, result.get("violations", [])[:3])
        assert result["violation_count"] == 0, method
        assert result.get("guaranteed") is True, method
        assert result["front_size"] >= 1, method
        assert len(result["plan"]) == 21, method
        assert set(result["objectives"]) == set(OBJECTIVE_NAMES), method
        for value in result["objectives"].values():
            assert math.isfinite(value), (method, value)


def test_new_algorithms_deterministic_under_fixed_seed():
    env = _ENVELOPES["t2d_htn"]
    for method in NEW_METHODS:
        a = solve(env, _DISHES, seed=9, pop_size=40, n_gen=8, method=method)
        b = solve(env, _DISHES, seed=9, pop_size=40, n_gen=8, method=method)
        assert a["plan"] == b["plan"], method
        assert a["objectives"] == b["objectives"], method
        assert a["engine"] == b["engine"], method


def test_raw_mode_returns_untouched_front_and_default_still_guaranteed():
    env = _ENVELOPES["ckd_strict"]
    raw = solve(env, _DISHES, seed=2, pop_size=40, n_gen=10, method="nsga3", guarantee=False)
    assert raw.get("guaranteed") is False
    assert raw["engine"] == "pymoo-raw"
    assert raw["front_size"] >= 1
    assert len(raw["plan"]) == 21
    assert all(math.isfinite(v) for v in raw["objectives"].values())
    # The guarantee path remains available and effective for the same method.
    guaranteed = solve(env, _DISHES, seed=2, pop_size=40, n_gen=10, method="nsga3")
    assert guaranteed["feasible"] is True
    assert guaranteed["violation_count"] == 0
    assert guaranteed.get("guaranteed") is True


def test_production_api_run_defaults_unchanged():
    """api.run keeps the NSGA-II + guarantee default (no method injection)."""
    env = _ENVELOPES["t2d_only"]
    result = run(env, seed=42, pop_size=10, n_gen=5)
    assert result["feasible"] is True
    assert result["violation_count"] == 0
    assert result.get("guaranteed", True) is True
    assert result["engine"] != "pymoo-raw"
    assert len(result["plan"]) == 21


def test_benchmark_artifacts_regen_and_parse():
    """Smoke-mode regeneration works and full artifacts stay parseable."""
    smoke_csv = os.path.join(_HERE_DIR, "benchmark_results_smoke.csv")
    smoke_md = os.path.join(_HERE_DIR, "benchmark_results_smoke.md")
    for path in (smoke_csv, smoke_md):
        if os.path.exists(path):
            os.remove(path)

    proc = subprocess.run(
        [sys.executable, "-m", "backend.optim.benchmark"],
        env={**os.environ, "CARELOOP_BENCH_SMOKE": "1"},
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert os.path.exists(smoke_csv) and os.path.exists(smoke_md)

    with open(smoke_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "smoke CSV has no data rows"
    header = set(rows[0])
    assert {"method", "guaranteed", "hypervolume", "runtime_ms", "feasible"} <= header
    methods = {r["method"] for r in rows}
    assert {"nsga2", "nsga3", "moead", "age", "sms"} <= methods
    assert "nsga3-raw" in methods and "sms-raw" in methods
    for row in rows:
        assert math.isfinite(float(row["hypervolume"])), row
        assert float(row["runtime_ms"]) >= 0.0
    smoke_md_text = open(smoke_md, encoding="utf-8").read()
    assert "## Recommendation" in smoke_md_text
    assert "nsga3" in smoke_md_text and "sms" in smoke_md_text
    for path in (smoke_csv, smoke_md):  # keep the package tree clean
        os.remove(path)

    # Full artifacts (regenerated by `python -m backend.optim.benchmark`).
    full_csv = os.path.join(_HERE_DIR, "benchmark_results.csv")
    full_md = os.path.join(_HERE_DIR, "benchmark_results.md")
    assert os.path.exists(full_csv) and os.path.exists(full_md)
    with open(full_csv, newline="", encoding="utf-8") as fh:
        full_rows = list(csv.DictReader(fh))
    assert full_rows
    assert {"method", "hypervolume", "runtime_ms"} <= set(full_rows[0])
    assert "## Recommendation" in open(full_md, encoding="utf-8").read()


TESTS = [
    test_real_pool_loads_214_dishes,
    test_envelopes_validate_against_schema,
    test_all_envelopes_pass_precheck,
    test_fast_evaluator_matches_canonical_evaluate,
    test_run_feasible_for_all_envelopes,
    test_run_deterministic_under_fixed_seed,
    test_run_tiny_budget_still_feasible,
    test_run_uses_real_dataset_by_default,
    test_infeasible_envelope_returns_diagnosis,
    test_exclusions_shrink_pool_as_expected,
    test_semantic_exclusion_mapping_filters_real_pool,
    test_new_algorithms_guaranteed_feasible_and_finite,
    test_new_algorithms_deterministic_under_fixed_seed,
    test_raw_mode_returns_untouched_front_and_default_still_guaranteed,
    test_production_api_run_defaults_unchanged,
    test_benchmark_artifacts_regen_and_parse,
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
