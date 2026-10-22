from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.optim import baselines, spike_pymoo
from backend.optim.problem import (
    OBJECTIVE_NAMES,
    EnvelopeNotApprovedError,
    evaluate,
    is_feasible,
)
from backend.optim.toy_data import TOY_DISHES
from shared.envelope_schema import EnvelopeStatus


def _envelope():
    return spike_pymoo.build_sample_envelope()


def _feasible_day() -> list[list[str]]:
    return [
        ["grilled_salmon_brown_rice"],
        ["yong_tau_foo_soup"],
        ["vegetable_bee_hoon"],
    ]


def test_feasible_plan_returns_true():
    plan = _feasible_day() * 7
    assert is_feasible(plan, _envelope(), TOY_DISHES) is True


def test_max_constraint_violation_returns_false():
    plan = [["nasi_lemak"]] * 21
    _, violations = evaluate(plan, _envelope(), TOY_DISHES)
    assert is_feasible(plan, _envelope(), TOY_DISHES) is False
    assert any(v["type"] == "max_daily" and v["nutrient"] == "sodium_mg" for v in violations)


def test_min_shortfall_is_soft_not_a_violation():
    plan = [["vegetable_bee_hoon"]] * 21
    objectives, violations = evaluate(plan, _envelope(), TOY_DISHES)
    assert is_feasible(plan, _envelope(), TOY_DISHES) is True
    assert violations == []
    assert all(v["type"] != "min_daily" for v in violations)
    assert objectives["nutrient_target_deviation"] >= 24.0 - 1e-6


def test_excluded_dish_returns_false():
    env = _envelope()

    lard_plan = [["char_kway_teow"], ["fish_soup_bee_hoon"], ["vegetable_bee_hoon"]] * 7
    assert is_feasible(lard_plan, env, TOY_DISHES) is False

    fried_plan = [["fried_chicken_wing_set"], ["fish_soup_bee_hoon"], ["vegetable_bee_hoon"]] * 7
    assert is_feasible(fried_plan, env, TOY_DISHES) is False

    _o, violations = evaluate(fried_plan, env, TOY_DISHES)
    assert any(v["type"] == "exclusion" for v in violations)


def test_unknown_dish_returns_false():
    plan = [["not_a_real_dish"], ["fish_soup_bee_hoon"], ["vegetable_bee_hoon"]] * 7
    assert is_feasible(plan, _envelope(), TOY_DISHES) is False


def test_evaluate_returns_four_objectives():
    objectives, violations = evaluate(_feasible_day() * 7, _envelope(), TOY_DISHES)
    assert set(objectives) == set(OBJECTIVE_NAMES)
    assert violations == []
    for value in objectives.values():
        assert isinstance(value, float)


def test_non_approved_envelope_raises():
    proposed = _envelope().model_copy(update={"status": EnvelopeStatus.PROPOSED})
    try:
        is_feasible(_feasible_day() * 7, proposed, TOY_DISHES)
    except EnvelopeNotApprovedError:
        pass
    else:  # pragma: no cover
        raise AssertionError("non-APPROVED envelope must be rejected")


def test_spike_produces_feasible_plan():
    result = spike_pymoo.run_spike(
        use_pymoo=False, pop_size=24, n_gen=30, seed=7, save_csv_file=False
    )
    assert result["front_size"] >= 1, "spike found no Pareto front (over-constrained?)"
    assert result["violation_count"] == 0, result["violations"]
    assert result["feasible"] is True


def test_baselines_run_and_return_plans():
    env = _envelope()
    rnd = baselines.random_search(env, TOY_DISHES, n_iter=200, seed=1)
    greedy = baselines.greedy_search(env, TOY_DISHES, seed=1)
    exhaustive = baselines.exhaustive_search(env, TOY_DISHES)
    for result in (rnd, greedy, exhaustive):
        assert len(result["plan"]) == 21
        assert set(result["objectives"]) == set(OBJECTIVE_NAMES)
    assert greedy["feasible"] is True
    assert exhaustive["feasible"] is True


TESTS = [
    test_feasible_plan_returns_true,
    test_max_constraint_violation_returns_false,
    test_min_shortfall_is_soft_not_a_violation,
    test_excluded_dish_returns_false,
    test_unknown_dish_returns_false,
    test_evaluate_returns_four_objectives,
    test_non_approved_envelope_raises,
    test_spike_produces_feasible_plan,
    test_baselines_run_and_return_plans,
]


def main() -> int:
    print("=" * 74)
    print("CareLoop optimiser smoke tests")
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
