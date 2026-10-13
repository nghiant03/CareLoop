"""Failure, retry-identity, and quantity-boundary regressions."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.app.api import review
from backend.app.core import persistence
from backend.app.models.patient import Patient
from backend.app.tests.test_core_api_regressions import (
    _isolated_stores,  # noqa: F401  # pytest fixture: isolate application state for every test
    _seed_review_item,
)


def test_retry_uses_exact_identity_after_unrelated_proposal(lenient_client, monkeypatch):
    review_id = _seed_review_item("core-exact-retry")
    original = persistence.finalize_review_proposal
    monkeypatch.setattr(persistence, "finalize_review_proposal", Mock(side_effect=RuntimeError("link failed")))
    first = lenient_client.post(f"/review/{review_id}/proposal")
    assert first.status_code == 500
    pending = persistence.get_review_item(review_id)
    assert pending is not None
    pending_id = pending["action"]["envelope_id"]
    unrelated = lenient_client.post("/rules/run", json={"patient_id": "P0002"})
    assert unrelated.status_code == 200
    unrelated_id = unrelated.json()["envelope"]["envelope_id"]
    assert unrelated_id != pending_id

    monkeypatch.setattr(persistence, "finalize_review_proposal", original)
    retry = lenient_client.post(f"/review/{review_id}/proposal")
    assert retry.status_code == 200, retry.text
    assert retry.json()["envelope_id"] == pending_id
    assert len(persistence.list_envelope_history("P0002")) == 2


def test_rejected_proposal_partial_success_is_recoverable(lenient_client, monkeypatch):
    # eGFR owns rejection independently of fixture diagnosis vocabulary.
    observed = lenient_client.post("/observations", json={
        "patient_id": "P0002", "metric": "egfr", "value": 10,
        "unit": "mL/min/1.73m2",
    })
    assert observed.status_code == 201
    review_id = _seed_review_item("core-rejected-retry")
    original = persistence.finalize_review_proposal
    monkeypatch.setattr(persistence, "finalize_review_proposal", Mock(side_effect=RuntimeError("link failed")))
    assert lenient_client.post(f"/review/{review_id}/proposal").status_code == 500
    history = persistence.list_envelope_history("P0002")
    assert len(history) == 1 and history[0]["status"] == "REJECTED"
    monkeypatch.setattr(persistence, "finalize_review_proposal", original)
    retry = lenient_client.post(f"/review/{review_id}/proposal")
    assert retry.status_code == 200, retry.text
    assert retry.json()["envelope_id"] == history[0]["envelope_id"]
    assert len(persistence.list_envelope_history("P0002")) == 1


def test_engine_failure_preserves_review_action(lenient_client, monkeypatch):
    review_id = _seed_review_item("core-engine-failure")
    persistence.record_review_action(review_id, "contacted", note="retain me")
    before = persistence.get_review_item(review_id)
    monkeypatch.setattr(review, "run_rules_service", Mock(side_effect=RuntimeError("engine failed")))
    assert lenient_client.post(f"/review/{review_id}/proposal").status_code == 500
    assert persistence.get_review_item(review_id) == before
    assert persistence.list_envelope_history("P0002") == []


def test_pending_attempt_reuses_the_committed_snapshot():
    from backend.app.api.patients import get_patient
    from backend.app.api.rules import run_rules_service

    review_id = _seed_review_item("core-pending-reuse")
    patient = get_patient("P0002")
    assert patient is not None
    with persistence.begin_review_proposal(review_id):
        first = run_rules_service(patient)["envelope"]
    # A second attempt reaches persistence after the first stored its identity.
    with persistence.begin_review_proposal(review_id):
        second = run_rules_service({**patient, "weight_kg": 99})["envelope"]
    assert second.model_dump() == first.model_dump()
    assert len(persistence.list_envelope_history("P0002")) == 1
    assert persistence.recover_pending_proposal(review_id) == first.envelope_id


def test_proposal_finalization_overlap_preserves_newer_pending(lenient_client, monkeypatch):
    review_id = _seed_review_item("core-overlapping-finalizers")
    original = persistence.finalize_review_proposal
    completions = []
    responses = {}

    def _interleaved_finalize(completing_review_id, envelope_id):
        completions.append(envelope_id)
        if len(completions) == 1:
            # A is paused before finalization; B recovers/finalizes A's E1.
            responses["B"] = lenient_client.post(f"/review/{review_id}/proposal")
            assert responses["B"].status_code == 200
            # C starts after B succeeded, persists fresh E2, then fails to link.
            responses["C"] = lenient_client.post(f"/review/{review_id}/proposal")
            assert responses["C"].status_code == 500
            return original(completing_review_id, envelope_id)  # A resumes.
        if len(completions) == 3:
            raise RuntimeError("C linkage failure")
        return original(completing_review_id, envelope_id)

    monkeypatch.setattr(persistence, "finalize_review_proposal", _interleaved_finalize)
    response_a = lenient_client.post(f"/review/{review_id}/proposal")
    assert response_a.status_code == 409, response_a.text
    assert response_a.json()["detail"] == {
        "error": "review_proposal_superseded", "review_id": review_id,
        "envelope_id": completions[0],
    }
    assert completions[0] == completions[1] == responses["B"].json()["envelope_id"]
    assert completions[2] != completions[0]
    pending = persistence.get_review_item(review_id)
    assert pending is not None
    assert pending["action"]["action"] == "proposal_pending"
    assert pending["action"]["envelope_id"] == completions[2]
    assert pending["linked_envelope_id"] == completions[0]

    monkeypatch.setattr(persistence, "finalize_review_proposal", original)
    retry_c = lenient_client.post(f"/review/{review_id}/proposal")
    assert retry_c.status_code == 200, retry_c.text
    assert retry_c.json()["envelope_id"] == completions[2]
    assert retry_c.json()["review_item"]["linked_envelope_id"] == completions[2]
    history = persistence.list_envelope_history("P0002")
    assert {row["envelope_id"] for row in history} == {completions[0], completions[2]}
    assert len(history) == 2  # No E3 was minted by C's retry.


def test_proposal_finalization_same_id_is_idempotent(client):
    review_id = _seed_review_item("core-idempotent-finalizer")
    response = client.post(f"/review/{review_id}/proposal")
    assert response.status_code == 200, response.text
    envelope_id = response.json()["envelope_id"]
    before = persistence.get_review_item(review_id)
    history = persistence.list_envelope_history("P0002")
    assert persistence.finalize_review_proposal(review_id, envelope_id) == before
    assert persistence.finalize_review_proposal(review_id, envelope_id) == before
    assert persistence.get_review_item(review_id) == before  # Timestamp unchanged.
    assert persistence.list_envelope_history("P0002") == history
    assert persistence.finalize_review_proposal("missing-review", envelope_id) is None


def test_proposal_finalization_preserves_clinician_action(lenient_client, monkeypatch):
    review_id = _seed_review_item("core-action-finalizer-conflict")
    original = persistence.finalize_review_proposal
    intervening = {}

    def _record_action_then_finalize(completing_review_id, envelope_id):
        intervening["row"] = persistence.record_review_action(
            completing_review_id, "contacted", note="do not overwrite",
        )
        intervening["envelope_id"] = envelope_id
        return original(completing_review_id, envelope_id)

    monkeypatch.setattr(persistence, "finalize_review_proposal", _record_action_then_finalize)
    response = lenient_client.post(f"/review/{review_id}/proposal")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "review_proposal_superseded"
    assert persistence.get_review_item(review_id) == intervening["row"]
    intervening_envelope_id = intervening["envelope_id"]
    assert isinstance(intervening_envelope_id, str)
    with pytest.raises(persistence.ReviewProposalConflictError):
        original(review_id, intervening_envelope_id)
    assert persistence.get_review_item(review_id) == intervening["row"]
    # Generic clinician actions deliberately retain their replacement contract.
    replacement = persistence.record_review_action(review_id, "resolved", note="new decision")
    assert replacement is not None
    assert replacement["action"]["action"] == "resolved"
    assert replacement["action"]["note"] == "new decision"


def test_pending_snapshot_and_identity_rollback_together(lenient_client):
    review_id = _seed_review_item("core-atomic-pending")
    before = persistence.get_review_item(review_id)
    with sqlite3.connect(persistence.db_path()) as conn:
        conn.execute("CREATE TRIGGER fail_pending BEFORE UPDATE OF action_json ON review_items "
                     "BEGIN SELECT RAISE(ABORT, 'injected pending failure'); END")
    try:
        assert lenient_client.post(f"/review/{review_id}/proposal").status_code == 500
        assert persistence.list_envelope_history("P0002") == []
        assert persistence.get_review_item(review_id) == before
    finally:
        with sqlite3.connect(persistence.db_path()) as conn:
            conn.execute("DROP TRIGGER fail_pending")
    assert lenient_client.post(f"/review/{review_id}/proposal").status_code == 200


def test_acknowledge_after_stale_open_read_preserves_action(client):
    review_id = _seed_review_item("core-stale-ack")
    stale = persistence.get_review_item(review_id)
    assert stale is not None
    assert stale["status"] == "OPEN"
    persistence.record_review_action(review_id, "contacted", note="new action")
    # This is the interleaving formerly vulnerable to the API's stale OPEN check.
    response = client.post(f"/review/{review_id}/acknowledge")
    assert response.status_code == 200
    assert response.json()["status"] == "ACTION_RECORDED"
    assert response.json()["acknowledged_at"] is None
    current = persistence.get_review_item(review_id)
    assert current is not None
    assert current["action"]["note"] == "new action"


@pytest.mark.parametrize("field", ["weight_kg", "height_cm", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL"])
@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN"])
def test_patient_all_declared_clinical_numerics_are_finite(client, field, value):
    record = {"patient_id": "core-finite", "age": 55, "sex": "F", "weight_kg": 70, field: value}
    with pytest.raises(ValidationError):
        Patient.model_validate(record)
    response = client.post("/patients", json=record)
    assert response.status_code == 422, response.text
    assert "core-finite" not in persistence.saved_patients()


def test_validation_error_nested_inputs_are_json_safe(client):
    response = client.post("/patients", content=(
        '{"patient_id":"core-nested", "sex":"F", "weight_kg":70, '
        '"age":{"bad":[Infinity,NaN,-Infinity]}}'
    ), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    error = response.json()["detail"][0]
    assert error["input"] == {"bad": ["inf", "nan", "-inf"]}
    assert "ctx" not in error


def test_patient_aliases_follow_both_observations_in_list(client):
    record = {"patient_id": "core-both-aliases", "age": 55, "sex": "F", "weight_kg": 70,
              "serum_K_meq_L": 4, "serum_k": 4, "serum_PO4_mg_dL": 3, "serum_po4": 3,
              "archetype": "preserve"}
    assert client.post("/patients", json=record).status_code == 201
    for metric, value, unit in [("serum_K_meq_L", 6.5, "mEq/L"), ("serum_PO4_mg_dL", 5.5, "mg/dL")]:
        response = client.post("/observations", json={"patient_id": record["patient_id"],
                                                    "metric": metric, "value": value, "unit": unit})
        assert response.status_code == 201
    patients = client.get("/patients").json()["patients"]
    current = next(patient for patient in patients if patient["patient_id"] == record["patient_id"])
    assert current["serum_k"] == current["serum_K_meq_L"] == 6.5
    assert current["serum_po4"] == current["serum_PO4_mg_dL"] == 5.5
    assert current["archetype"] == "preserve"


def test_legacy_schema_initializes_across_processes(tmp_path):
    database = tmp_path / "concurrent-legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE meal_logs (patient_id TEXT NOT NULL, date TEXT NOT NULL, "
                     "meal TEXT NOT NULL, dish_id TEXT NOT NULL, logged_at TEXT NOT NULL, "
                     "PRIMARY KEY (patient_id, date, meal))")
        conn.execute("INSERT INTO meal_logs VALUES ('legacy', '2026-10-10', 'lunch', 'dish', 'receipt')")
    environment = {**os.environ, "CARELOOP_APP_DB": str(database)}
    code = "from backend.app.core import persistence; input(); persistence.init_db()"
    workers = [subprocess.Popen([sys.executable, "-c", code], env=environment,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True) for _ in range(4)]
    try:
        for worker in workers:
            assert worker.stdin is not None
            worker.stdin.write("start\n")
            worker.stdin.flush()
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=30)
            assert worker.returncode == 0, (stdout, stderr)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
    with sqlite3.connect(database) as conn:
        assert [column[1] for column in conn.execute("PRAGMA table_info(meal_logs)")].count("items_json") == 1
        assert conn.execute("SELECT dish_id, items_json FROM meal_logs").fetchone() == ("dish", None)


@pytest.mark.parametrize("unit", ["mL/min", "mL/min/1.73m2", "mL/min/1.73m²"])
def test_egfr_unit_spellings_preserve_indexed_value(client, unit):
    response = client.post("/observations", json={"patient_id": "P0001", "metric": "egfr",
                                                "value": 42, "unit": unit})
    assert response.status_code == 201, response.text
    assert response.json()["value"] == 42
    assert response.json()["unit"] == "mL/min/1.73m2"
