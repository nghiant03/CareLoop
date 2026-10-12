"""Chat endpoint identity resolution (backend/app/api/chat.py).

Regression coverage for explicitly requested patient/envelope identities:

* Unknown IDs return 404 instead of degrading to anonymous guideline chat.
* Patient/envelope identity conflicts return 409 instead of mixing one
  patient's envelope with another patient's profile context.
* Explicit envelopes derive applicability/weight context from their own patient.
* Omitting both IDs keeps anonymous guideline chat.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app

_SODIUM_QUESTION = "What is my daily sodium limit?"


def _envelope_id_for(client: TestClient, patient_id: str) -> str:
    body = client.post("/rules/run", json={"patient_id": patient_id}).json()
    return body["envelope"]["envelope_id"]


def test_unknown_explicit_patient_rejected_404() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/chat", json={"patient_id": "P9999", "message": _SODIUM_QUESTION}
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["error"] == "patient_not_found"


def test_unknown_explicit_envelope_rejected_404() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/chat",
            json={"envelope_id": "ENV-DOES-NOT-EXIST", "message": _SODIUM_QUESTION},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["error"] == "envelope_not_found"


def test_patient_envelope_identity_conflict_rejected_409() -> None:
    """One patient's envelope must never be answered with another patient's
    profile context: P0019's envelope requested together with P0001's
    patient_id is a 409, not a mixed-context answer."""
    with TestClient(app) as client:
        envelope_id = _envelope_id_for(client, "P0019")
        resp = client.post(
            "/chat",
            json={
                "patient_id": "P0001",
                "envelope_id": envelope_id,
                "message": _SODIUM_QUESTION,
            },
        )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["error"] == "patient_envelope_mismatch"
        assert detail["patient_id"] == "P0001"
        assert detail["envelope_id"] == envelope_id


def test_envelope_id_derives_context_from_its_own_patient() -> None:
    with TestClient(app) as client:
        envelope_id = _envelope_id_for(client, "P0019")
        resp = client.post(
            "/chat", json={"envelope_id": envelope_id, "message": _SODIUM_QUESTION}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "answered"


def test_omitted_ids_keep_anonymous_guideline_chat() -> None:
    with TestClient(app) as client:
        resp = client.post("/chat", json={"message": "why is my sodium limit 2000?"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "answered"
        assert body["citations"]
