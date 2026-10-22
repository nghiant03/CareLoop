import pytest

from backend.app.api import rules
from backend.app.chat.answers import _envelope_context
from backend.app.core import approval_policy, envelope_lifecycle
from shared.envelope_schema import NutrientEnvelope

PATIENT = {"patient_id": "POLICY", "age": 60, "sex": "M", "weight_kg": 70}


@pytest.fixture
def saved(monkeypatch):
    snapshots = []

    def put(envelope, *, new_proposal=False):
        envelope.lifecycle_revision += 1
        snapshots.append(envelope.model_copy(deep=True))
        return envelope

    monkeypatch.setattr(rules, "put_envelope", put)
    monkeypatch.setattr(envelope_lifecycle, "put_envelope", put)
    return snapshots


def engine_result(**changes):
    envelope = NutrientEnvelope.model_validate({
        "envelope_id": "ENV-POLICY-001", "patient_id": "POLICY",
        "patient_snapshot": PATIENT, "priority_basis": "synthetic policy test",
        "targets": [{"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"}],
        **changes,
    })
    return {"envelope": envelope.model_dump(), "trace": []}


def test_default_auto_uses_lifecycle_and_preserves_proposal_snapshot(saved, monkeypatch):
    monkeypatch.delenv("CARELOOP_APPROVAL_MODE", raising=False)
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result())
    envelope = rules.run_rules_service(PATIENT)["envelope"]
    assert [snapshot.status.value for snapshot in saved] == ["PROPOSED", "APPROVED"]
    assert envelope.approved_by == approval_policy.AUTO_APPROVAL_ACTOR
    assert envelope.approved_at is not None
    assert envelope.lifecycle_revision == 2 and envelope.version == 1


def test_clinician_mode_only_saves_proposal(saved, monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "clinician")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result())
    envelope = rules.run_rules_service(PATIENT)["envelope"]
    assert envelope.status.value == "PROPOSED" and envelope.approved_by is None
    assert len(saved) == 1


@pytest.mark.parametrize("changes", [
    {"status": "REJECTED", "targets": []},
    {"scope_eligible": False}, {"targets": []},
])
def test_auto_does_not_approve_ineligible_or_targetless_results(saved, monkeypatch, changes):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result(**changes))
    envelope = rules.run_rules_service(PATIENT)["envelope"]
    assert envelope.status.value != "APPROVED"
    assert len(saved) == 1


def test_invalid_mode_fails_before_engine_or_persistence(saved, monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "automatic")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: pytest.fail("engine must not run"))
    with pytest.raises(ValueError, match="CARELOOP_APPROVAL_MODE"):
        rules.run_rules_service(PATIENT)
    assert saved == []


def test_invalid_mode_prevents_application_startup(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main

    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "invalid")
    monkeypatch.setattr(main, "init_db", lambda: pytest.fail("invalid policy reached storage"))
    with pytest.raises(ValueError, match="CARELOOP_APPROVAL_MODE"), TestClient(main.app):
        pass


def test_public_config_exposes_only_approval_mode(monkeypatch):
    from backend.app.main import public_config

    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    assert public_config() == {"approval_mode": "auto"}


def test_auto_edit_still_clears_approval(saved, monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result())
    approved = rules.run_rules_service(PATIENT)["envelope"]
    edited = envelope_lifecycle.edit(approved, edited_by="simulated reviewer", notes="manual edit")
    assert edited.status.value == "EDITED"
    assert edited.approved_by is None and edited.approved_at is None
    assert approved.status.value == "APPROVED"


def test_chat_identifies_historical_auto_approval_independent_of_current_mode(monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "clinician")
    envelope = engine_result(status="APPROVED", approved_by=approval_policy.AUTO_APPROVAL_ACTOR)["envelope"]
    context = _envelope_context(envelope, ["sodium_mg"])
    assert context is not None
    assert "auto-approved demo" in context["sentence"]
    assert "not clinically reviewed" in context["sentence"]
    assert "clinician-approved" not in context["sentence"]


@pytest.fixture
def runtime_mode():
    yield approval_policy
    approval_policy.reset_approval_mode()


def test_runtime_switch_overrides_configured_default_until_reset(runtime_mode, saved, monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result())
    assert runtime_mode.set_approval_mode("clinician") == "clinician"
    assert rules.run_rules_service(PATIENT)["envelope"].status.value == "PROPOSED"
    assert runtime_mode.reset_approval_mode() == "auto"
    assert rules.run_rules_service(PATIENT)["envelope"].status.value == "APPROVED"


def test_runtime_switch_to_auto_keeps_scope_and_edit_rules(runtime_mode, saved, monkeypatch):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "clinician")
    runtime_mode.set_approval_mode("auto")
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result(scope_eligible=False))
    assert rules.run_rules_service(PATIENT)["envelope"].status.value != "APPROVED"
    monkeypatch.setattr(rules, "engine_run_rules", lambda _: engine_result())
    approved = rules.run_rules_service(PATIENT)["envelope"]
    assert approved.approved_by == approval_policy.AUTO_APPROVAL_ACTOR
    edited = envelope_lifecycle.edit(approved, edited_by="simulated reviewer", notes="manual edit")
    assert edited.status.value == "EDITED" and edited.approved_by is None


def test_runtime_switch_rejects_unknown_mode_and_invalid_configuration(runtime_mode, monkeypatch):
    with pytest.raises(ValueError, match="auto or clinician"):
        runtime_mode.set_approval_mode("approve-everything")
    runtime_mode.set_approval_mode("clinician")
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "invalid")
    with pytest.raises(ValueError, match="CARELOOP_APPROVAL_MODE"):
        runtime_mode.approval_mode()


def test_approval_mode_endpoint_switches_public_config(runtime_mode, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main

    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    client = TestClient(main.app)
    response = client.put("/config/approval-mode", json={"approval_mode": "clinician"})
    assert response.status_code == 200 and response.json() == {"approval_mode": "clinician"}
    assert main.public_config() == {"approval_mode": "clinician"}
    assert client.put("/config/approval-mode", json={"approval_mode": "yes"}).status_code == 422
    assert main.public_config() == {"approval_mode": "clinician"}
