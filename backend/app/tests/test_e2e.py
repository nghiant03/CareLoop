"""End-to-end API tests: patient -> rules/run -> approve -> plans -> chat.

Exercises the full wired loop through the FastAPI app (TestClient, lifespan
included so the knowledge base warms up):

* happy path: PROPOSED envelope with per-constraint citations -> clinician
  approval -> 7-day plan (21 slots, zero hard-constraint violations, totals vs
  targets, plain-language explanation panel);
* the approval gate still answers the documented 409 before approval;
* chat: grounded answer with a guideline citation, escalation for
  out-of-scope questions;
* out-of-scope patient (pregnancy) -> REJECTED envelope with a clear reason;
* mining + kb observability endpoints with deterministic shapes.

NOTE on fibre floors: the guideline rulebook sets hard MIN fibre floors
(25/30 g per day) that the real 214-dish dataset cannot reach (max 8 g per
dish). ``POST /plans`` lowers unreachable floors to the achievable pool bound
and discloses them in ``relaxed_constraints`` — this is the documented
cross-lane reconciliation; ``violation_count == 0`` holds against the envelope
actually solved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _run_rules(client, patient_id: str) -> dict:
    resp = client.post("/rules/run", json={"patient_id": patient_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Full happy path
# ---------------------------------------------------------------------------


def test_full_happy_path(client) -> None:
    # 1) patient -> PROPOSED envelope + traceable fired-rule trace
    body = _run_rules(client, "P0001")
    envelope, trace = body["envelope"], body["trace"]
    assert envelope["status"] == "PROPOSED"
    assert envelope["patient_id"] == "P0001"
    assert envelope["targets"], "expected nutrient targets"
    assert trace, "expected a fired-rule trace"

    # Frontend trace contract: rule_id, priority, guideline, section, url.
    for row in trace:
        assert row["rule_id"]
        assert isinstance(row["priority"], int)
        assert row["citation"]["guideline"]
        assert row["citation"]["section"]
        assert row["citation"]["url"] or row["citation"]["url"] is None

    # >= 1 citation covering every target nutrient (traceability per constraint)
    summaries = " ".join(row["action_summary"] for row in trace).lower()
    for target in envelope["targets"]:
        nutrient = target["nutrient"].rsplit("_", 1)[0]
        assert nutrient in summaries, f"{nutrient} not traceable in the trace"
    assert envelope["citations"], "envelope must carry citations"

    # 2) clinician approves (frontend alias body {clinician_id, note})
    envelope_id = envelope["envelope_id"]
    approved = client.post(
        f"/envelopes/{envelope_id}/approve",
        json={"clinician_id": "dr-tan", "note": "e2e approval"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_by"] == "dr-tan"

    # 3) clinician explanation endpoint
    expl = client.get(f"/envelopes/{envelope_id}/explanation")
    assert expl.status_code == 200, expl.text
    explanation = expl.json()
    assert explanation["fired_rules"]
    assert explanation["constraints"]
    for constraint in explanation["constraints"]:
        assert constraint["citation"], "constraints must carry citations"
        assert constraint["citation"]["guideline"]

    # 4) approved envelope -> 7-day plan, zero hard-constraint violations
    plan_resp = client.post("/plans", json={"patient_id": "P0001"})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    assert plan["feasible"] is True, plan.get("infeasibility_reason")
    assert plan["violation_count"] == 0
    assert plan["envelope_id"] == envelope_id
    assert len(plan["days"]) == 7
    for day in plan["days"]:
        assert len(day["slots"]) == 3
        assert day["totals"]
        for slot in day["slots"]:
            assert slot["dish_id"] and slot["name"]
            assert slot["meal"] in ("breakfast", "lunch", "dinner")
        for total in day["totals"]:
            assert total["targets"] or total["value"]
    # fibre floor relaxation must be disclosed (dataset cannot reach 25/30 g)
    assert any(
        rc["nutrient"] == "fiber_g" for rc in plan["relaxed_constraints"]
    ), "expected the documented fibre-floor relaxation to be disclosed"
    # plain-language explanation panel payload
    assert plan["explanation"]["daily_targets"]
    assert plan["explanation"]["why"]

    # every hard constraint (incl. relaxed floors) satisfied every day
    for day in plan["days"]:
        for total in day["totals"]:
            if total["compliant"] is False:
                pytest.fail(f"hard constraint violated: {total}")


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


def test_gate_blocks_before_approval(client) -> None:
    _run_rules(client, "P0002")
    resp = client.post("/plans", json={"patient_id": "P0002"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "envelope_not_approved"
    assert resp.json()["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def test_chat_grounded_answer_with_citation(client) -> None:
    _run_rules(client, "P0003")  # give the patient an envelope
    resp = client.post(
        "/chat",
        json={"patient_id": "P0003", "message": "why is my sodium limit 2000?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["escalated"] is False
    assert body["status"] == "answered"
    assert "KDIGO" in body["answer"]
    assert body["citations"], "grounded answers must cite"
    for citation in body["citations"]:
        assert citation["rule_id"]
        assert citation["guideline"]
    assert any("kdigo" in (c["guideline"] or "").lower() for c in body["citations"])


def test_chat_escalation(client) -> None:
    resp = client.post(
        "/chat", json={"patient_id": "P0001", "message": "I have chest pain"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["escalated"] is True
    assert body["citations"] == []
    assert "emergency" in body["answer"].lower() or "clinician" in body["answer"].lower()


def test_chat_refuses_unknown_topics(client) -> None:
    resp = client.post(
        "/chat", json={"patient_id": "P0001", "message": "What is the capital of France?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["escalated"] is False
    assert body["status"] == "refused"
    assert body["citations"] == []
    assert "clinician" in body["answer"].lower()


def test_chat_flags_unapproved_envelope(client) -> None:
    _run_rules(client, "P0004")  # PROPOSED, deliberately not approved
    resp = client.post(
        "/chat",
        json={"patient_id": "P0004", "message": "why is my sodium limit 2000?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "answered"
    assert "not been approved" in body["answer"]


# ---------------------------------------------------------------------------
# Out-of-scope patient path
# ---------------------------------------------------------------------------


def test_out_of_scope_patient_rejected_envelope(client) -> None:
    body = _run_rules(client, "P0008")  # pregnancy -> out of scope
    envelope = body["envelope"]
    assert envelope["status"] == "REJECTED"
    assert envelope["targets"] == []
    assert "OUT OF SCOPE" in envelope["notes"]
    assert body["trace"], "out-of-scope trace still explains why"

    expl = client.post("/plans", json={"patient_id": "P0008"})
    assert expl.status_code == 409, expl.text
    assert expl.json()["error"] == "envelope_not_approved"


# ---------------------------------------------------------------------------
# Mining + KB observability
# ---------------------------------------------------------------------------


def test_mining_trends_deterministic(client) -> None:
    first = client.get("/mining/trends")
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"count", "flags"}
    assert body["count"] == len(body["flags"])
    for flag in body["flags"]:
        assert flag["patient_id"]
        assert flag["analyte"] in ("K", "PO4")
        assert flag["severity"] in ("urgent", "review")
        assert "slope_per_month" in flag and "projected_3mo" in flag
    second = client.get("/mining/trends")
    assert second.json() == body  # deterministic


def test_mining_substitutions_deterministic(client) -> None:
    first = client.get("/mining/substitutions", params={"dish_id": "SG0001", "k": 3})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["dish_id"] == "SG0001"
    assert len(body["substitutions"]) == 3
    for sub in body["substitutions"]:
        assert sub["dish_id"] != "SG0001"
        assert sub["name"]
        assert isinstance(sub["distance"], float)
        assert sub["reason"]
    second = client.get("/mining/substitutions", params={"dish_id": "SG0001", "k": 3})
    assert second.json() == body  # deterministic


def test_mining_substitutions_unknown_dish(client) -> None:
    resp = client.get("/mining/substitutions", params={"dish_id": "NOPE", "k": 3})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dish_not_found"


def test_kb_stats(client) -> None:
    resp = client.get("/kb/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_counts"]["Rule"] >= 50
    assert body["node_counts"]["Dish"] == 214
    assert body["retrieval_chunks"] >= body["node_counts"]["Rule"]
    assert body["current_version"]


def test_patients_list_ui_shape(client) -> None:
    resp = client.get("/patients")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == len(body["patients"])
    for patient in body["patients"]:
        assert patient["id"] == patient["patient_id"]
        assert isinstance(patient["diagnoses"], list)
        assert "serum_k" in patient and "serum_po4" in patient
        assert "meds" in patient and "age" in patient and "sex" in patient