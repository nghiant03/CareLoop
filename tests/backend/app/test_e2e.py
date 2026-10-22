from __future__ import annotations

import pytest


def _run_rules(client, patient_id: str) -> dict:
    resp = client.post("/rules/run", json={"patient_id": patient_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_happy_path(client) -> None:
    body = _run_rules(client, "P0001")
    envelope, trace = body["envelope"], body["trace"]
    assert envelope["status"] == "PROPOSED"
    assert envelope["patient_id"] == "P0001"
    assert envelope["targets"], "expected nutrient targets"
    assert trace, "expected a fired-rule trace"

    for row in trace:
        assert row["rule_id"]
        assert isinstance(row["priority"], int)
        assert row["citation"]["guideline"]
        assert row["citation"]["section"]
        assert row["citation"]["url"] or row["citation"]["url"] is None

    summaries = " ".join(row["action_summary"] for row in trace).lower()
    for target in envelope["targets"]:
        nutrient = target["nutrient"].rsplit("_", 1)[0]
        assert nutrient in summaries, f"{nutrient} not traceable in the trace"
    assert envelope["citations"], "envelope must carry citations"

    envelope_id = envelope["envelope_id"]
    approved = client.post(
        f"/envelopes/{envelope_id}/approve",
        json={"clinician_id": "dr-tan", "note": "e2e approval"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_by"] == "dr-tan"

    expl = client.get(f"/envelopes/{envelope_id}/explanation")
    assert expl.status_code == 200, expl.text
    explanation = expl.json()
    assert explanation["fired_rules"]
    assert explanation["constraints"]
    for constraint in explanation["constraints"]:
        assert constraint["citation"], "constraints must carry citations"
        assert constraint["citation"]["guideline"]

    plan_resp = client.post("/plans", json={"patient_id": "P0001"})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    assert plan["feasible"] is True, plan.get("infeasibility_reason")
    assert plan["violation_count"] == 0
    assert plan["envelope_id"] == envelope_id
    assert len(plan["days"]) == 7
    for day in plan["days"]:
        assert {s["meal"] for s in day["slots"]} == {"breakfast", "lunch", "dinner"}
        assert 3 <= len(day["slots"]) <= 6
        assert day["totals"]
        for slot in day["slots"]:
            assert slot["dish_id"] and slot["name"]
            assert slot["meal"] in ("breakfast", "lunch", "dinner")
        for total in day["totals"]:
            assert total["targets"] or total["value"]
    assert plan["relaxed_constraints"] == []
    assert all(a["met_days"] == 7 for a in plan["adequacy"] if a["nutrient"] == "fiber_g")
    assert plan["explanation"]["daily_targets"]
    assert plan["explanation"]["why"]

    for day in plan["days"]:
        for total in day["totals"]:
            if total["compliant"] is False:
                pytest.fail(f"hard constraint violated: {total}")


def test_gate_blocks_before_approval(client) -> None:
    _run_rules(client, "P0002")
    resp = client.post("/plans", json={"patient_id": "P0002"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "envelope_not_approved"
    assert resp.json()["status"] == "PROPOSED"


def test_chat_grounded_answer_with_citation(client) -> None:
    _run_rules(client, "P0003")
    resp = client.post(
        "/chat",
        json={"patient_id": "P0003", "message": "why is my sodium limit 2000?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["escalated"] is False
    assert body["status"] == "answered"
    assert "AHA/ACC" in body["answer"]
    assert "KDIGO" not in body["answer"]
    assert body["citations"], "grounded answers must cite"
    for citation in body["citations"]:
        assert citation["rule_id"]
        assert citation["guideline"]
    assert any("aha/acc" in (c["guideline"] or "").lower() for c in body["citations"])


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
    _run_rules(client, "P0004")
    resp = client.post(
        "/chat",
        json={"patient_id": "P0004", "message": "why is my sodium limit 2000?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "answered"
    assert "not been approved" in body["answer"]


def test_out_of_scope_patient_rejected_envelope(client) -> None:
    body = _run_rules(client, "P0008")
    envelope = body["envelope"]
    assert envelope["status"] == "REJECTED"
    assert envelope["targets"] == []
    assert "OUT OF SCOPE" in envelope["notes"]
    assert body["trace"], "out-of-scope trace still explains why"

    expl = client.post("/plans", json={"patient_id": "P0008"})
    assert expl.status_code == 409, expl.text
    assert expl.json()["error"] == "envelope_not_approved"


def test_rejected_envelope_cannot_be_approved(client) -> None:
    body = _run_rules(client, "P0008")
    envelope_id = body["envelope"]["envelope_id"]
    assert body["envelope"]["status"] == "REJECTED"

    approved = client.post(
        f"/envelopes/{envelope_id}/approve",
        json={"clinician_id": "dr-tan", "note": "override attempt"},
    )
    assert approved.status_code == 422, approved.text
    assert approved.json()["error"] == "out_of_scope_envelope"

    after = client.get(f"/envelopes/{envelope_id}")
    assert after.status_code == 200
    assert after.json()["status"] == "REJECTED"
    plan = client.post("/plans", json={"patient_id": "P0008"})
    assert plan.status_code == 409, plan.text
    assert plan.json()["error"] == "envelope_not_approved"


def test_chat_declined_scope_response_for_rejected_patient(client) -> None:
    _run_rules(client, "P0008")
    resp = client.post(
        "/chat",
        json={"patient_id": "P0008", "message": "how much potassium can I have?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["escalated"] is False
    assert "declined" in body["answer"]
    assert "clinician" in body["answer"]
    assert body["citations"] == []


def test_edit_appends_clinician_edit_trace_row(client) -> None:
    body = _run_rules(client, "P0013")
    envelope_id = body["envelope"]["envelope_id"]

    edited = client.post(
        f"/envelopes/{envelope_id}/edit",
        json={
            "targets": [
                {"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"}
            ],
            "edited_by": "dr-tan",
            "notes": "tightened sodium",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "EDITED"

    expl = client.get(f"/envelopes/{envelope_id}/explanation")
    assert expl.status_code == 200, expl.text
    rule_ids = [row["rule_id"] for row in expl.json()["fired_rules"]]
    assert "CLINICIAN-EDIT" in rule_ids


def test_rerun_mints_new_envelope_and_preserves_approval(client) -> None:
    first = _run_rules(client, "P0011")["envelope"]
    first_id = first["envelope_id"]
    client.post(f"/envelopes/{first_id}/approve", json={"clinician_id": "dr-tan"})

    second = _run_rules(client, "P0011")["envelope"]
    second_id = second["envelope_id"]
    assert second_id != first_id, "re-run must mint a new envelope id"

    still_there = client.get(f"/envelopes/{first_id}")
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "APPROVED"

    latest = client.post("/plans", json={"patient_id": "P0011"})
    assert latest.status_code == 409, latest.text
    assert latest.json()["status"] == "PROPOSED"


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
    assert second.json() == body


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
    assert second.json() == body


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
