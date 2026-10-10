"""Boundary regressions for chat identity, legacy units, and claim grounding."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api import chat as chat_api
from backend.app.chat import answers, escalation


@pytest.mark.parametrize("field", ["patient_id", "envelope_id"])
def test_blank_explicit_identity_is_not_anonymous(field, monkeypatch):
    monkeypatch.setattr(chat_api, "get_patient", lambda _: None)
    monkeypatch.setattr(chat_api, "get_envelope", lambda _: None)
    with pytest.raises(HTTPException) as exc:
        chat_api.chat(chat_api.ChatRequest(message="sodium?", **{field: ""}))
    assert exc.value.status_code == 404


def test_explicit_envelope_passes_its_patient_context(monkeypatch):
    envelope = SimpleNamespace(
        patient_id="envelope-patient",
        model_dump=lambda **_: {"patient_id": "envelope-patient"},
    )
    profile = {"patient_id": "envelope-patient", "weight_kg": 70}
    monkeypatch.setattr(chat_api, "get_envelope", lambda _: envelope)
    requested = []
    monkeypatch.setattr(chat_api, "get_patient", lambda pid: requested.append(pid) or profile)
    monkeypatch.setattr(chat_api, "get_kb", lambda: object())
    captured = {}

    def capture_answer(question, kb, **context):
        captured.update(context)
        return {"answer": "grounded", "citations": [], "status": "refused"}

    monkeypatch.setattr(chat_api.answers, "answer", capture_answer)
    chat_api.chat(chat_api.ChatRequest(message="sodium?", envelope_id="explicit"))
    assert requested == ["envelope-patient"]
    assert captured["patient"] is profile


@pytest.mark.parametrize("reading, expected", [
    ("350 mg/dL", True), ("349.9 mg/dL", False),
    ("500 mg/dL", True), ("10000 mg/dL", True),
    ("19.5 mmol/L", True), ("19.4 mmol/L", False),
    ("above 300 mg/dL", True), ("above 299 mg/dL", False),
    ("above 17 mmol/L", True), ("above 16 mmol/L", False),
])
def test_glucose_units_and_existing_category_boundaries(reading, expected):
    result = escalation.check(f"My blood sugar is {reading}; what can I eat?")
    assert result["escalate"] is expected
    if expected:
        assert result["category"] == "emergency"


def test_legacy_clinician_value_equal_to_old_coefficient_is_absolute():
    target = {"nutrient": "protein_g", "kind": "max", "value": 1.3, "unit": "g"}
    trace = [
        {"rule_id": "old-rule", "priority": 80,
         "action_summary": "set protein_g max = 1.3 g/kg/d",
         "citation": {"rule_id": "old-rule"}},
        {"rule_id": "CLINICIAN-EDIT",
         "action_summary": "set protein_g max = 1.3 g",
         "citation": {"rule_id": "CLINICIAN-EDIT"}},
    ]
    assert not answers._target_is_unscaled_per_kg({"fired_rules": trace}, target)


def test_legacy_scaling_uses_the_selected_source_not_any_matching_row():
    target = {
        "nutrient": "protein_g", "kind": "max", "value": 1.3, "unit": "g",
        "provenance": {
            "nutrient": "protein_g", "kind": "max", "value": 1.3, "unit": "g",
            "citation": {"rule_id": "absolute-rule"},
        },
    }
    trace = [
        {"rule_id": "raw-rule", "action_summary": "set protein_g max = 1.3 g/kg/d"},
        {"rule_id": "absolute-rule", "action_summary": "set protein_g max = 1.3 g"},
    ]
    assert not answers._target_is_unscaled_per_kg({"fired_rules": trace}, target)


def test_personal_target_with_incomplete_source_is_withheld():
    target = {
        "nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg",
        "provenance": {
            "nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg",
            "citation": {"guideline": "unidentified source"},
        },
    }
    context = answers._envelope_context(
        {"status": "APPROVED", "targets": [target]}, ["sodium_mg"],
    )
    assert context["citation"] is None


@pytest.mark.parametrize("question", [
    "What should my sugar intake be?", "Recommend my sugar allowance",
    "What is an appropriate amount of sugar for me?",
])
def test_unsupported_intake_never_borrows_protein_citation(question, monkeypatch):
    citation = {"rule_id": "protein-rule", "guideline": "Protein", "section": "1"}
    hit = {"chunk_id": "rule:protein-rule", "kind": "rule", "score": 10,
           "citation": citation}
    monkeypatch.setattr(answers.retrieval, "build_index", lambda _: SimpleNamespace(
        retrieve=lambda *args, **kwargs: [hit],
    ))
    kb = SimpleNamespace(rules_for_nutrient=lambda _: [])
    result = answers.answer(question, kb)
    assert result["status"] == "refused"
    assert result["citations"] == []


@pytest.mark.parametrize("status, notice", [
    ("APPROVED", None),
    ("PROPOSED", "This plan has not been approved by a clinician yet."),
    ("EDITED", "This plan has not been approved by a clinician yet."),
])
def test_lifecycle_notice_is_independent_of_matched_target(status, notice, monkeypatch):
    citation = {"rule_id": "sodium-rule", "guideline": "Sodium", "section": "1"}
    rule = {**citation, "constraints": [
        {"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"},
    ]}
    monkeypatch.setattr(answers.retrieval, "build_index", lambda _: SimpleNamespace(
        retrieve=lambda *args, **kwargs: [],
    ))
    kb = SimpleNamespace(rules_for_nutrient=lambda _: [rule])
    envelope = {"envelope_id": "test", "status": status, "targets": [
        {"nutrient": "protein_g", "kind": "max", "value": 40, "unit": "g"},
    ]}
    result = answers.answer("What is my sodium limit?", kb, envelope=envelope)
    assert result["status"] == "answered"
    assert result["envelope"]["approved"] is (status == "APPROVED")
    assert result["envelope"]["notice"] == notice


def test_uncited_personal_assertion_is_not_supported_by_independent_anchor(monkeypatch):
    citation = {"rule_id": "sodium-rule", "guideline": "Sodium", "section": "1"}
    rule = {**citation, "constraints": [
        {"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"},
    ]}
    kb = SimpleNamespace(rules_for_nutrient=lambda _: [rule])
    monkeypatch.setattr(answers.retrieval, "build_index", lambda _: SimpleNamespace(
        retrieve=lambda *args, **kwargs: [],
    ))
    envelope = {"envelope_id": "test", "status": "APPROVED", "targets": [
        {"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"},
    ]}
    result = answers.answer("What is my sodium limit?", kb, envelope=envelope)
    assert result["status"] == "answered"
    assert "1.8 g" not in result["answer"]
    assert all(claim["source"] == "rule" for claim in result["claims"])
    assert all(
        all(claim["citation"][key] == value for key, value in citation.items())
        for claim in result["claims"]
    )


def test_food_content_is_not_mistaken_for_unsupported_intake(monkeypatch):
    citation = {"rule_id": "food-rule", "guideline": "Food", "section": "1",
                "verbatim_quote": "Limit sugary drinks."}
    rule = {**citation, "constraints": []}
    hits = [
        {"chunk_id": "rule:food-rule", "kind": "rule", "score": 10,
         "citation": citation},
        {"chunk_id": "dish:drink", "kind": "dish", "score": 9,
         "meta": {"dish_id": "drink", "name": "Drink", "nutrients": {"sugar_g": 8}}},
    ]
    kb = SimpleNamespace(rules_for_nutrient=lambda _: [], get_rule=lambda _: rule)
    monkeypatch.setattr(answers.retrieval, "build_index", lambda _: SimpleNamespace(
        retrieve=lambda *args, **kwargs: hits,
    ))
    result = answers.answer("How much sugar is in this drink?", kb)
    assert result["status"] == "answered"
    assert "8 g" in result["answer"]
    assert any(claim.get("chunk_id") == "dish:drink" for claim in result["claims"])
