"""Transition, concurrency, and trace regressions using isolated durable state."""

import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.core import envelope_lifecycle, persistence
from backend.app.core.approval_gate import get_envelope
from backend.app.core.trace_store import put_trace, trace_or_none
from backend.app.main import app
from shared.envelope_schema import NutrientEnvelope
from shared.export_schema import SCHEMA_PATH, schema_text


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CARELOOP_APP_DB", str(tmp_path / "clinical.sqlite3"))
    with TestClient(app) as client:
        yield client


def propose(api, patient_id="P0001"):
    response = api.post("/rules/run", json={"patient_id": patient_id})
    assert response.status_code == 200, response.text
    return response.json()["envelope"]


def test_scope_rejection_cannot_be_cleared_by_editing_targets_and_notes(api):
    original = propose(api, "P0008")
    assert original["status"] == "REJECTED" and not original["scope_eligible"]
    path = f"/envelopes/{original['envelope_id']}"
    edited = api.post(path + "/edit", json={
        "targets": [{"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"}],
        "notes": "New clinician note",
    })
    assert edited.status_code == 422
    assert api.post(path + "/approve", json={}).status_code == 422
    assert api.get(path).json() == original
    assert len(persistence.list_envelope_history("P0008")) == 1


def test_legacy_scope_snapshot_retains_exclusion_after_note_change(api):
    legacy = propose(api, "P0008")
    del legacy["scope_eligible"]
    del legacy["lifecycle_revision"]
    restored = NutrientEnvelope.model_validate(legacy)
    restored.notes = "Updated note"
    assert not restored.scope_eligible
    with pytest.raises(envelope_lifecycle.EnvelopeScopeError):
        envelope_lifecycle.edit(restored, edited_by="reviewer")


def test_stale_approval_cannot_overwrite_an_edit_from_another_worker(api):
    original = propose(api)
    stale = get_envelope(original["envelope_id"])
    script = """
import sys
from backend.app.core.approval_gate import get_envelope
from backend.app.core.envelope_lifecycle import edit
envelope = get_envelope(sys.argv[1])
targets = [t.model_copy(deep=True) for t in envelope.targets]
next(t for t in targets if t.nutrient.value == 'sodium_mg').value = 1234
edit(envelope, edited_by='second-worker', targets=targets)
"""
    subprocess.run([sys.executable, "-c", script, stale.envelope_id],
                   env=os.environ.copy(), check=True, capture_output=True, text=True)
    with pytest.raises(persistence.EnvelopeConflictError):
        envelope_lifecycle.approve(stale, approved_by="stale-reviewer")
    current = get_envelope(stale.envelope_id)
    assert current.version == 2 and current.status.value == "EDITED"
    assert next(t.value for t in current.targets if t.nutrient.value == "sodium_mg") == 1234
    assert len(persistence.list_envelope_history("P0001")) == 2


@pytest.mark.parametrize("action,payload", [
    ("approve", {}), ("edit", {"notes": "stale edit"}), ("reject", {"reason": "stale rejection"}),
])
def test_client_revision_detects_stale_actions_even_when_version_is_unchanged(api, action, payload):
    original = propose(api)
    path = f"/envelopes/{original['envelope_id']}"
    approved = api.post(path + "/approve", json={"expected_revision": original["lifecycle_revision"]})
    assert approved.status_code == 200
    assert approved.json()["version"] == original["version"]
    assert approved.json()["lifecycle_revision"] == original["lifecycle_revision"] + 1
    stale = api.post(path + "/" + action, json={**payload, "expected_revision": original["lifecycle_revision"]})
    assert stale.status_code == 409
    assert stale.json()["error"] == "envelope_conflict"
    assert api.get(path).json() == approved.json()


def test_durable_trace_wins_over_a_stale_process_cache(api):
    original = propose(api)
    eid = original["envelope_id"]
    put_trace(eid, original["fired_rules"])
    api.post(f"/envelopes/{eid}/edit", json={"notes": "new trace event"})
    current = get_envelope(eid)
    assert trace_or_none(current)[-1]["rule_id"] == "CLINICIAN-EDIT"
    assert len(trace_or_none(current)) == len(original["fired_rules"]) + 1
    empty = current.model_copy(update={"fired_rules": []})
    assert trace_or_none(empty) == []


def test_generated_schema_validates_actual_lifecycle_responses(api):
    assert SCHEMA_PATH.read_text() == schema_text(), "Run python -m shared.export_schema"
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    original = propose(api)
    validator.validate(original)
    path = f"/envelopes/{original['envelope_id']}"
    edited = api.post(path + "/edit", json={"targets": original["targets"], "edited_by": "schema-test"})
    validator.validate(edited.json())
    assert edited.json()["targets"][0]["provenance"]["author"] == "schema-test"
    validator.validate(api.post(path + "/approve", json={}).json())
