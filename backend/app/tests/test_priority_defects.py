"""Regressions for proposal concurrency, finite targets, and raw plan decisions."""

import pytest
from pydantic import ValidationError

from backend.app.api import review
from backend.app.core import persistence
from backend.app.core.plan_service import map_plan_result
from backend.app.tests.test_core_api_regressions import (
    _isolated_stores,  # noqa: F401  # pytest fixture: isolate journal and review state
    _seed_review_item,
)
from backend.app.tests.test_plan_adequacy import _dish, _envelope, _result
from shared.envelope_schema import NutrientConstraint, NutrientEnvelope


def test_proposal_computation_preserves_competing_clinician_action(client, monkeypatch):
    review_id = _seed_review_item("priority-computing-action")
    original = review.run_rules_service
    competing = {}

    def record_action_then_compute(patient):
        competing["row"] = persistence.record_review_action(
            review_id, "contacted", note="retain this decision",
        )
        return original(patient)

    monkeypatch.setattr(review, "run_rules_service", record_action_then_compute)
    response = client.post(f"/review/{review_id}/proposal")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "review_proposal_superseded"
    assert persistence.get_review_item(review_id) == competing["row"]
    assert persistence.list_envelope_history("P0002") == []

    # A deliberate request after the action is still allowed to create a proposal.
    monkeypatch.setattr(review, "run_rules_service", original)
    assert client.post(f"/review/{review_id}/proposal").status_code == 200
    assert len(persistence.list_envelope_history("P0002")) == 1


def test_stale_computation_cannot_mint_after_other_attempt_finalizes():
    from backend.app.api.patients import get_patient

    review_id = _seed_review_item("priority-computing-overlap")
    patient = get_patient("P0002")
    assert patient is not None
    with persistence.begin_review_proposal(review_id):
        with persistence.begin_review_proposal(review_id):
            first = review.run_rules_service(patient)["envelope"]
        completed = persistence.finalize_review_proposal(review_id, first.envelope_id)
        with pytest.raises(persistence.ReviewProposalConflictError):
            review.run_rules_service(patient)
    assert persistence.get_review_item(review_id) == completed
    assert len(persistence.list_envelope_history("P0002")) == 1


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), "Infinity", "-Infinity", "NaN"])
def test_constraint_model_rejects_nonfinite_values(value):
    with pytest.raises(ValidationError):
        NutrientConstraint(nutrient="sodium_mg", kind="max", value=value, unit="mg")


@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN"])
def test_nonfinite_edits_and_simulations_do_not_change_durable_state(client, value):
    proposed = client.post("/rules/run", json={"patient_id": "P0002"})
    assert proposed.status_code == 200, proposed.text
    envelope_id = proposed.json()["envelope"]["envelope_id"]
    approved = client.post(f"/envelopes/{envelope_id}/approve")
    assert approved.status_code == 200, approved.text
    before = client.get(f"/envelopes/{envelope_id}").json()
    history = persistence.list_envelope_history("P0002")
    target = {"nutrient": "sodium_mg", "kind": "max", "value": value, "unit": "mg"}

    for path, payload in [
        (f"/envelopes/{envelope_id}/edit", {"targets": [target]}),
        ("/simulations", {"patient_id": "P0002", "targets": [target]}),
    ]:
        response = client.post(path, json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["error"] == "validation_error"
    assert client.get(f"/envelopes/{envelope_id}").json() == before
    assert persistence.list_envelope_history("P0002") == history
    assert persistence.list_simulations("P0002") == []


def test_nonfinite_explicit_provenance_is_rejected():
    target = NutrientConstraint(nutrient="sodium_mg", kind="max", value=1000, unit="mg")
    envelope = _envelope("finite-provenance", [target]).model_dump(mode="json")
    envelope["targets"][0]["provenance"] = {
        "nutrient": "sodium_mg", "kind": "max", "value": "Infinity", "unit": "mg",
        "envelope_id": envelope["envelope_id"], "version": 1, "author": "test",
        "citation": {"rule_id": "TEST", "guideline": "Test", "section": "Sodium"},
    }
    with pytest.raises(ValidationError):
        NutrientEnvelope.model_validate(envelope)


@pytest.mark.parametrize(("aim", "delivery", "compliant"), [
    (1000.0006, 1000.0006, True),
    (1000.0001, 1000.0002, False),
])
def test_max_compliance_uses_unrounded_delivery(aim, delivery, compliant):
    envelope = _envelope("raw-max", [NutrientConstraint(
        nutrient="sodium_mg", kind="max", value=aim, unit="mg",
    )])
    dishes = [_dish("delivery", sodium_mg=delivery)]
    out = map_plan_result(_result([["delivery"], [], []]), envelope, dishes)
    total = next(row for row in out["days"][0]["totals"] if row["nutrient"] == "sodium_mg")
    assert total["value"] == round(delivery, 3)
    assert total["compliant"] is compliant


@pytest.mark.parametrize(("kind", "delivery", "met"), [
    ("min", 1000.0002, 0),
    ("target", 1000.0004, 1),
    ("target", 1000.0006, 0),
])
def test_adequacy_and_relaxation_use_unrounded_original_aim(kind, delivery, met):
    envelope = _envelope("raw-aim", [NutrientConstraint(
        nutrient="sodium_mg", kind=kind, value=1000.0004, unit="mg",
    )])
    out = map_plan_result(_result([["delivery"], [], []]), envelope,
                          [_dish("delivery", sodium_mg=delivery)])
    entry = out["adequacy"][0]
    assert entry["met_days"] == met
    assert entry["relaxed_aim"] is None
    assert out["adequate"] is bool(met)


def test_adequacy_percentage_is_rounded_only_after_raw_calculation():
    envelope = _envelope("raw-percentage", [NutrientConstraint(
        nutrient="sodium_mg", kind="min", value=1.0004, unit="mg",
    )])
    out = map_plan_result(_result([["delivery"], [], []]), envelope,
                          [_dish("delivery", sodium_mg=0.5)])
    assert out["adequacy"][0]["shortfall_pct"] == round((1.0004 - 0.5) / 1.0004 * 100, 3)
