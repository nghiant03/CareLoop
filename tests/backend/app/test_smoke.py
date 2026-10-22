from __future__ import annotations

import asyncio

import httpx

from backend.app.main import app

BASE_URL = "http://testserver"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE_URL
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_run())


def test_imports() -> None:
    from backend.app.core import approval_gate, graph_versioning, llm_choice
    from backend.app.models import NutrientEnvelope, Patient

    assert NutrientEnvelope is not None
    assert Patient is not None
    assert approval_gate.require_approved_envelope is not None
    assert graph_versioning.GraphStore is not None
    assert llm_choice.choose_llm() is not None


def test_healthz() -> None:
    resp = _request("GET", "/healthz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "careloop-backend"


def test_get_patient_may_be_404() -> None:
    resp = _request("GET", "/patients/p-1")
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 404:
        assert resp.json()["detail"]["error"] == "patient_not_found"


def test_create_patient_roundtrip() -> None:
    payload = {
        "patient_id": "p-smoke",
        "name": "Smoke Test",
        "age": 61,
        "sex": "F",
        "weight_kg": 68.0,
        "diagnoses": ["T2D", "HTN", "CKD_stage_3"],
        "egfr": 42.0,
        "serum_K_meq_L": 4.9,
        "serum_PO4_mg_dL": 4.1,
        "meds": ["metformin"],
    }
    created = _request("POST", "/patients", json=payload)
    assert created.status_code == 201, created.text
    fetched = _request("GET", "/patients/p-smoke")
    assert fetched.status_code == 200
    assert fetched.json()["diagnoses"] == ["T2D", "HTN", "CKD_stage_3"]


def test_rules_run_returns_proposed_envelope() -> None:
    patient = {
        "patient_id": "p-smoke-rules",
        "age": 61,
        "sex": "F",
        "weight_kg": 68.0,
        "diagnoses": ["T2D", "HTN", "CKD_stage_3"],
        "egfr": 42.0,
        "serum_K_meq_L": 4.9,
        "serum_PO4_mg_dL": 4.1,
        "meds": ["metformin"],
    }
    resp = _request("POST", "/rules/run", json=patient)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    envelope = body["envelope"]
    assert envelope["status"] == "PROPOSED"
    assert envelope["patient_id"] == "p-smoke-rules"
    assert len(envelope["targets"]) >= 1
    assert len(envelope["fired_rules"]) >= 1
    assert envelope["priority_basis"]
    assert isinstance(body["trace"], list) and body["trace"]


def test_rules_run_by_patient_id() -> None:
    resp = _request("POST", "/rules/run", json={"patient_id": "P0001"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["envelope"]["patient_id"] == "P0001"
    assert body["envelope"]["status"] == "PROPOSED"


def test_rules_run_unknown_patient_404() -> None:
    resp = _request("POST", "/rules/run", json={"patient_id": "NOPE-999"})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "patient_not_found"


def test_approval_gate_blocks_until_approved() -> None:
    patient = {
        "patient_id": "p-gate",
        "age": 58,
        "sex": "M",
        "weight_kg": 72.0,
        "diagnoses": ["CKD_stage_4"],
        "egfr": 22.0,
    }
    proposed = _request("POST", "/rules/run", json=patient)
    assert proposed.status_code == 200, proposed.text
    envelope_id = proposed.json()["envelope"]["envelope_id"]

    blocked = _request("POST", "/plans", json={"patient_id": "p-gate"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json() == {
        "error": "envelope_not_approved",
        "status": "PROPOSED",
    }

    approved = _request("POST", f"/envelopes/{envelope_id}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    after = _request("POST", "/plans", json={"patient_id": "p-gate"})
    assert after.status_code in (200, 501), after.text
    assert after.status_code != 409


def test_edit_invalidates_approval() -> None:
    patient = {
        "patient_id": "p-edit",
        "age": 65,
        "sex": "F",
        "weight_kg": 60.0,
        "diagnoses": ["HTN"],
    }
    env = _request("POST", "/rules/run", json=patient).json()["envelope"]
    _request("POST", f"/envelopes/{env['envelope_id']}/approve", json={})
    edited = _request(
        "POST", f"/envelopes/{env['envelope_id']}/edit", json={"notes": "tweak"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "EDITED"
    blocked = _request("POST", "/plans", json={"patient_id": "p-edit"})
    assert blocked.status_code == 409, blocked.text


def test_chat_grounded_contract() -> None:
    resp = _request("POST", "/chat", json={"message": "What can I eat?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("answered", "refused", "escalated")
    assert isinstance(body["citations"], list)
    assert body["escalated"] is False
    if body["status"] == "answered":
        assert body["citations"], "answered chat must cite the KB"


if __name__ == "__main__":
    import sys

    try:
        import pytest

        raise SystemExit(pytest.main([__file__, "-v"]))
    except ImportError:
        failures = 0
        tests = [
            (name, obj)
            for name, obj in sorted(globals().items())
            if name.startswith("test_") and callable(obj)
        ]
        for name, fn in tests:
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc!r}")
        print(f"\n{len(tests) - failures}/{len(tests)} passed")
        sys.exit(1 if failures else 0)
