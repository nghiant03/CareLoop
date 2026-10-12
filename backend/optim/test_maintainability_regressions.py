"""Boundary regressions for search delivery, policy reuse, and helper contracts."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from backend.optim import baselines, benchmark, problem, real_data, solver, toy_data
from backend.optim.exact_reference import one_day_exact
from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


def _envelope():
    return NutrientEnvelope(
        envelope_id="env-boundary", patient_id="p-boundary", version=1,
        status=EnvelopeStatus.APPROVED,
        patient_snapshot=PatientSummary(patient_id="p-boundary", age=50, sex="M", weight_kg=70),
        targets=[NutrientConstraint(
            nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX,
            value=3.0, unit="mg",
        )],
        priority_basis="test",
    )


def _dish(did="safe", sodium=0.5):
    return toy_data.Dish(
        dish_id=did, name=did, category="test",
        nutrients={"sodium_mg": sodium}, price_sgd=1,
    )


@pytest.mark.parametrize("search", [
    baselines.random_search, baselines.greedy_search, baselines.exhaustive_search,
    solver.greedy_search, solver.random_search,
])
def test_empty_search_is_delivery_failure_but_evaluator_stays_hard_only(search):
    env = _envelope()
    assert problem.evaluate([], env, [])[1] == []
    result = search(env, [])
    assert result["plan"] == []
    assert result["feasible"] is False
    assert result["violations"][0]["type"] == "search_failure"


def test_failed_greedy_construction_is_not_feasible(monkeypatch):
    monkeypatch.setattr(solver, "greedy_feasible_plan", lambda *a, **kw: None)
    result = solver.greedy_search(_envelope(), [_dish()])
    assert result["feasible"] is False
    assert result["plan"] == []


@pytest.mark.parametrize("method", ["nsga3", "moead", "age", "sms"])
@pytest.mark.parametrize("has_core", [True, False])
def test_unavailable_comparison_algorithms_raise_actionable_error(monkeypatch, method, has_core):
    monkeypatch.setattr(solver, "HAS_PYMOO", has_core)
    monkeypatch.setattr(solver, "HAS_PYMOO_EXTRAS", False)
    monkeypatch.setattr(solver, "PYMOO_EXTRAS_IMPORT_ERROR", "ImportError: optional module missing")
    with pytest.raises(RuntimeError, match="optional module missing"):
        solver.solve(_envelope(), [_dish()], method=method)


def test_nsga2_fallback_survives_missing_optional_algorithms(monkeypatch):
    monkeypatch.setattr(solver, "HAS_PYMOO", False)
    monkeypatch.setattr(solver, "HAS_PYMOO_EXTRAS", False)
    result = solver.solve(_envelope(), [_dish()], pop_size=4, n_gen=1)
    assert result["feasible"] is True
    assert len(result["plan"]) == problem.SLOTS


def test_benchmark_hv_winner_is_not_deployment_recommendation(tmp_path, monkeypatch):
    output = tmp_path / "benchmark.md"
    monkeypatch.setattr(benchmark, "MD_PATH", str(output))
    entries = [({
        "phase": "main", "envelope": "test", "method": method,
        "hypervolume": hv, "runtime_ms": runtime, "feasible": 1,
    }, None) for method, hv, runtime in [("nsga2", "0.4", 10), ("sms", "0.8", 100)]]
    benchmark._write_report(entries, {}, 0)
    text = output.read_text()
    assert "Highest guaranteed-method HV: sms" in text
    assert "10.0x" in text
    assert "not a deployment recommendation" in text
    assert "Algorithm recommendation: sms" not in text


def test_daily_tolerance_does_not_prove_repeated_week_feasible():
    env = _envelope()
    dish = _dish(sodium=1.0 + problem.EPS / 6)
    day = [[dish.dish_id]] * problem.MEALS_PER_DAY
    assert one_day_exact(env, [dish])["feasible_day"] is True
    assert problem.evaluate(day, env, [dish])[1] == []
    violations = problem.evaluate(day * problem.DAYS, env, [dish])[1]
    assert [v["scope"] for v in violations] == ["horizon"]
    ev = real_data.FastEvaluator(env, [dish])
    daily = np.array([[0.0] * len(problem.NUTRIENT_KEYS)] * problem.DAYS)
    daily[:, problem.NUTRIENT_KEYS.index("sodium_mg")] = 3 * dish.nutrient("sodium_mg")
    assert ev.day_violation(daily[0]) == (0, 0.0)
    assert ev.g_vector(daily)[-1] > 0


@pytest.mark.parametrize("cap,complete", [(1, False), (8, True), (9, True), (0, False)])
def test_bounded_enumeration_exposes_completion(cap, complete):
    result = baselines.exhaustive_search(_envelope(), [_dish("a"), _dish("b")], max_combos=cap)
    assert result["search_complete"] is complete
    assert result["evaluations"] == min(cap, 8)


def test_empty_enumeration_is_complete_but_not_delivered():
    result = baselines.exhaustive_search(_envelope(), [])
    assert result["search_complete"] is True
    assert result["feasible"] is False


@pytest.mark.parametrize("filename", ["test_exact.py", "test_selection.py"])
def test_fixture_dependent_modules_direct_users_to_pytest(filename):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(filename))],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "python -m pytest" in result.stderr
    assert "TypeError" not in result.stderr


def test_fast_evaluator_uses_canonical_weights_and_tolerance():
    assert real_data.EPS == problem.EPS
    assert real_data._SCALAR_WEIGHT_VEC.tolist() == [
        problem.SCALAR_WEIGHTS[name] for name in problem.OBJECTIVE_NAMES
    ]
    ev = real_data.FastEvaluator(_envelope(), [_dish()])
    objectives = {name: float(i + 1) for i, name in enumerate(problem.OBJECTIVE_NAMES)}
    vector = np.array([objectives[name] for name in problem.OBJECTIVE_NAMES])
    assert ev.scalar(vector) == pytest.approx(problem.scalar_score(objectives))


def test_toy_loader_default_and_explicit_nested_schema(tmp_path):
    assert toy_data.load_dishes() == toy_data.TOY_DISHES
    assert toy_data.load_dishes(str(tmp_path / "absent.json")) == toy_data.TOY_DISHES
    path = tmp_path / "nested.json"
    path.write_text(json.dumps([{
        "dish_id": "nested", "name": "Nested", "category": "test",
        "nutrients": {"sodium_mg": 123},
    }]))
    assert toy_data.load_dishes(str(path))[0].nutrient("sodium_mg") == 123


def test_toy_loader_rejects_flat_catalogue(tmp_path):
    path = tmp_path / "flat.json"
    path.write_text(json.dumps([{
        "dish_id": "flat", "name": "Flat", "category": "test", "sodium_mg": 123,
    }]))
    with pytest.raises(ValueError, match="real_data.load_dishes"):
        toy_data.load_dishes(str(path))
