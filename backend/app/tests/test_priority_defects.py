"""Regressions for proposal concurrency, finite targets, and raw plan decisions."""

import pytest
from pydantic import ValidationError

from backend.app.api import review
from backend.app.core import persistence
from backend.app.core.plan_service import map_plan_result
from backend.app.tests.test_core_api_regressions import (
    _isolated_stores,  # isolate journal and review state for every test
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
    with persistence.begin_review_proposal(review_id):
        with persistence.begin_review_proposal(review_id):
            first = review.run_rules_service(patient)["envelope"]
        completed = persistence.finalize_review_proposal(review_id, first.envelope_id)
        with pytest.raises(persistence.ReviewProposalConflictError):
            review.run_rules_service(patient)
    assert persistence.get_review_item(review_id) == completed
    assert len(persistence.list_envelope_history("P0002")) == 1
