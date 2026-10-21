"""Live approval policy, persisted history and downstream gates."""

import pytest

from backend.app.core import persistence
from backend.app.core.approval_policy import AUTO_APPROVAL_ACTOR


@pytest.mark.parametrize("mode,status", [("auto", "APPROVED"), ("clinician", "PROPOSED")])
def test_rules_apply_policy_and_preserve_history(client, monkeypatch, mode, status):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", mode)
    response = client.post("/rules/run", json={"patient_id": "P0001"})
    assert response.status_code == 200, response.text
    envelope = response.json()["envelope"]
    assert envelope["status"] == status
    assert client.get("/config").json() == {"approval_mode": mode}
    saved = client.get(f"/envelopes/{envelope['envelope_id']}").json()
    assert saved == envelope
    history = [row for row in persistence.list_envelope_history("P0001")
               if row["envelope_id"] == envelope["envelope_id"]]
    assert [row["status"] for row in history] == (["PROPOSED", "APPROVED"] if mode == "auto" else ["PROPOSED"])
    if mode == "auto":
        assert envelope["approved_by"] == AUTO_APPROVAL_ACTOR
        assert envelope["approved_at"] and envelope["lifecycle_revision"] == 2
        assert client.post("/plans", json={"patient_id": "P0001"}).status_code == 200
        chat = client.post("/chat", json={"patient_id": "P0001", "message": "What is my daily sodium limit?"})
        assert chat.status_code == 200
        assert "not clinically reviewed" in chat.text
        edited = client.post(f"/envelopes/{envelope['envelope_id']}/edit", json={
            "notes": "simulated human edit", "expected_revision": envelope["lifecycle_revision"],
        })
        assert edited.status_code == 200 and edited.json()["status"] == "EDITED"
    assert client.post("/plans", json={"patient_id": "P0001"}).status_code == 409


@pytest.mark.parametrize("fields", [
    {"pregnant": True}, {"age": 12}, {"diagnoses": ["dialysis"]},
    {"diagnoses": ["CKD_stage_5"]}, {"egfr": 10},
])
def test_auto_preserves_scope_rejections(client, monkeypatch, fields):
    monkeypatch.setenv("CARELOOP_APPROVAL_MODE", "auto")
    patient = {"patient_id": "AUTO-SCOPE", "age": 60, "sex": "F", "weight_kg": 70,
               "diagnoses": ["T2D"], **fields}
    response = client.post("/rules/run", json=patient)
    assert response.status_code == 200, response.text
    envelope = response.json()["envelope"]
    assert envelope["status"] == "REJECTED" and envelope["approved_at"] is None
    assert client.post("/plans", json={"patient_id": "AUTO-SCOPE"}).status_code == 409
