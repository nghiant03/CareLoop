"""Evaluator verification fixtures, excluded from every real-data benchmark."""

import hashlib
from copy import deepcopy
from types import SimpleNamespace

import pytest

from careloop.evaluation.language import answer_score, rule_score
from careloop.evaluation.oracle import audit
from careloop.evaluation.planning import benchmark
from careloop.evaluation.runner import reuse_language_cache, validate_references
from careloop.evaluation.storage import claim, freeze, read, write
from careloop.evaluation.substitutions import benchmark as substitutions
from careloop.foods.models import FoodBody
from careloop.inference import Settings
from careloop.planning.search import generate


def case():
    foods = []
    for identity, energy in (("a", 100), ("b", 150), ("c", 200)):
        body = FoodBody.model_validate(
            {
                "name": f"Evaluator fixture {identity}",
                "category": "Test fixture",
                "nutrients": {"energy": energy, "protein": 10, "carbohydrate": 20, "fat": 5},
                "portions": [{"id": "serving", "label": "Fixture serving", "grams": 100}],
                "meal_slots": ["lunch"],
                "planning_portions": ["serving"],
                "review_note": "Evaluator unit test, not benchmark data",
                "provenance": {"kind": "manual", "source": "test://evaluation", "notes": "Fixture"},
            }
        ).model_dump(mode="json")
        foods.append({"id": identity, "latest_revision": 1, "body": body})
    return {
        "id": "unit-test-only",
        "provenance": {"kind": "test_fixture"},
        "request": {"days": 1, "schedule": ["lunch"], "items_per_slot": {}},
        "facts": {
            "allergies": [],
            "vegetarian": False,
            "include_eggs": True,
            "include_dairy": True,
            "dislikes": None,
        },
        "items": [
            {
                "action": {
                    "kind": "range",
                    "subject": "energy",
                    "amount": 140,
                    "upper": 160,
                    "unit": "kcal/day",
                }
            }
        ],
        "foods": foods,
    }


def test_independent_oracle_detects_tampered_snapshots_and_portions():
    problem = case()
    alternatives, _ = generate(
        problem["foods"], SimpleNamespace(**problem["request"]), problem["facts"], problem["items"]
    )
    meals = alternatives[0]["meals"]
    assert audit(meals, problem)["valid"]
    changed = deepcopy(meals)
    changed[0]["quantity"] = "1"
    assert "quantity_or_unit_mismatch" in audit(changed, problem)["violations"]
    changed = deepcopy(meals)
    changed[0]["food"]["nutrients"]["energy"] = 0
    assert "food_snapshot_mismatch" in audit(changed, problem)["violations"]
    assert not audit([], problem)["valid"]


def test_planning_compares_exact_baselines_without_filling_missing_preferences():
    result = benchmark(case(), random_seeds=(1, 2), random_budget=20)
    assert result["state"] == "completed"
    assert not result["preferences_measured"]
    assert result["exact"]["metadata"]["search_space"] == 9
    assert {method["method"] for method in result["methods"]} == {
        "beam",
        "greedy",
        "random",
        "exact",
    }
    exact = result["exact"]["alternatives"]
    assert all(a["independent_audit"]["valid"] for a in exact)
    assert all(a["absolute_optimality_gap"] == 0 for a in exact)


def test_missing_real_prerequisites_are_blocked_not_synthesized():
    problem = case()
    problem["facts"]["allergies"] = None
    result = benchmark(problem)
    assert result["state"] == "blocked"
    assert result["methods"] == []
    assert problem["facts"]["allergies"] is None


def test_substitution_checks_use_independent_feasible_pool():
    problem = case()
    alternatives, _ = generate(
        problem["foods"], SimpleNamespace(**problem["request"]), problem["facts"], problem["items"]
    )
    result = substitutions(problem, alternatives[0]["meals"], clusters=1)
    assert result["state"] == "completed"
    assert len(result["tasks"]) == 3
    assert all(task["invalid_suggestions"] == 0 for task in result["tasks"])
    assert all(task["feasible_foods"] > 0 for task in result["tasks"])


def test_extraction_scoring_penalizes_extra_actions_and_wrong_predicates():
    action = {"kind": "intake", "subject": "protein", "amount": 0.8, "unit": "g/kg/day"}
    expected = {
        "expected_rules": [
            {"action": action, "applicability": [], "exceptions": [], "blocker_required": True}
        ]
    }
    correct = {"action": action, "applicability": [], "exceptions": [], "blockers": ["Review"]}
    assert rule_score({"rules": [correct]}, expected)["bounded_pass"]
    extra = rule_score({"rules": [correct, correct]}, expected)
    assert extra["action_precision"] == 0.5 and not extra["bounded_pass"]
    wrong = {**correct, "applicability": [{"fact": "age_years", "operator": "gte", "value": 18}]}
    assert not rule_score({"rules": [wrong]}, expected)["bounded_pass"]


def test_ablation_expects_abstention_not_factual_answer_from_memory():
    expected = {
        "source_ids": ["real-source"],
        "expected": {
            "needs_clinician": False,
            "insufficient_evidence": False,
            "required_patterns": ["0\\.8"],
        },
    }
    abstention = {
        "answer": "The supplied sources do not provide the requested target.",
        "needs_clinician": False,
        "insufficient_evidence": True,
        "citations": [],
    }
    assert answer_score(abstention, expected, [], ablated=True)["bounded_pass"]
    assert not answer_score(abstention, expected, ["real-source"])["bounded_pass"]


def test_freeze_and_claim_never_overwrite_inputs_or_repeat_pending_work(tmp_path):
    path = tmp_path / "manifest.json"
    freeze(path, {"version": 1})
    freeze(path, {"version": 1})
    with pytest.raises(ValueError, match="Frozen inputs differ"):
        freeze(path, {"version": 2})
    request = tmp_path / "request.json"
    assert claim(request, {"id": "a"})
    assert not claim(request, {"id": "b"})
    assert read(request)["id"] == "a" and read(request)["state"] == "pending"


def test_document_split_validation_rejects_question_leakage():
    corpus = {
        "documents": [
            {"id": "a", "split": "dev", "official_url": "https://a.example"},
            {"id": "b", "split": "test", "official_url": "https://b.example"},
        ],
        "passages": [
            {
                "id": "p",
                "document_id": "a",
                "content": "Real text",
                "reference_extraction": {"rules": []},
            }
        ],
        "questions": [{"id": "q", "split": "test", "passage_ids": ["p"]}],
    }
    with pytest.raises(ValueError, match="crosses document split"):
        validate_references(corpus)


def test_cache_reuse_preserves_failed_attempts_and_rejects_changed_inference(tmp_path, monkeypatch):
    from careloop.evaluation import language

    source, target = tmp_path / "old", tmp_path / "new"
    task = {"case_id": "same", "payload": {"model": "example"}}
    monkeypatch.setattr(language, "tasks", lambda *args: [task])
    monkeypatch.setattr(Settings, "load", lambda: Settings("https://test.example/", "test-only"))
    hashes = dict.fromkeys(
        ("inference.py", "answers.py", "evidence/extraction.py", "evaluation/language.py"), "same"
    )
    manifest = {"code_sha256": hashes, "references": {}, "models": []}
    write(source / "manifest.json", manifest)
    write(target / "manifest.json", manifest)
    write(
        source / "catalogue.json",
        {"endpoint_sha256": hashlib.sha256(b"https://test.example/").hexdigest()},
    )
    saved = {"id": "attempt", "task": task, "state": "failed", "error": "Timeout"}
    write(source / "requests/attempt.json", saved)
    assert reuse_language_cache(source, target) == 1
    assert read(target / "requests/attempt.json") == saved
    assert reuse_language_cache(source, target) == 0
    manifest["code_sha256"]["answers.py"] = "changed"
    write(target / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Cannot reuse calls after"):
        reuse_language_cache(source, target)
