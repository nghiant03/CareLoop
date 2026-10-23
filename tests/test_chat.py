import json
from copy import deepcopy
from uuid import uuid4

from test_inference import response
from test_logging import planned, setup_plan
from test_patients import CLINICIAN, REVIEWER, approve, patient, propose, rule
from test_planning import PATIENT, approve_plan, food, ready, request

from careloop.inference import InferenceError, Settings, configured_client


class Provider:
    settings = Settings("https://test.example/v1/", "test-key")

    def __init__(self):
        self.calls = 0
        self.during_call = None
        self.error = None
        self.source_id = "approved-targets"

    def complete(self, **payload):
        self.calls += 1
        self.payload = payload
        if self.during_call:
            self.during_call()
        if self.error:
            raise InferenceError(self.error)
        return response(
            {
                "answer": "Your recorded target is a sodium ceiling of 100 mg/day.",
                "source_ids": [self.source_id],
                "needs_clinician": False,
                "insufficient_evidence": False,
            }
        )


def setup(client):
    evidence, body = rule(client)
    p = patient(client)
    t = propose(client, p)
    assert approve(client, t).status_code == 200
    provider = Provider()
    client.app.dependency_overrides[configured_client] = lambda: provider
    data = {
        **PATIENT,
        "request_id": str(uuid4()),
        "question": "What is my sodium target?",
        "patient_revision": 1,
        "target_id": t["id"],
        "target_revision": t["latest_revision"],
    }
    return p, t, provider, data, evidence, body


def test_chat_uses_approved_context_and_retains_cited_history(client):
    p, t, provider, data, evidence, body = setup(client)
    path = f"/api/patients/{p['id']}/chat"
    ctx = client.get(path + "/context").json()
    assert ctx["ready"] and ctx["target_id"] == t["id"]
    assert ctx["facts"]["pregnant"] is None
    # An unpublished edit must not replace the active evidence quotation.
    changed = deepcopy(body)
    changed["action"]["advice"] = "Unpublished advice"
    assert (
        client.post(
            f"/api/evidence/rules/{evidence['id']}/revisions",
            json={
                **REVIEWER,
                "expected_revision": 1,
                "body": changed,
            },
        ).status_code
        == 201
    )
    first = client.post(path, json=data)
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["state"] == "completed"
    assert run["context"]["patient_revision"] == 1
    assert run["result"]["citations"][0]["kind"] == "approved_target"
    assert "100" in run["result"]["citations"][0]["quote"]
    assert "test-key" not in first.text and "request" not in run and "response" not in run
    assert provider.payload["model"] == "glm-5.3"
    assert provider.payload["response_format"]["type"] == "json_object"
    content = json.loads(provider.payload["messages"][1]["content"])
    assert "display_name" not in content["sources"][0]["text"]
    source = next(s for s in content["sources"] if s["kind"] == "published_evidence")
    assert source["id"].endswith(":1") and source["text"] == body["quote"]
    assert client.post(path, json=data).json() == run and provider.calls == 1
    assert client.post(path, json={**data, "question": "Different"}).status_code == 409
    assert client.get(path).json() == [run]
    assert client.get(path + "/" + data["request_id"]).json() == run
    next_data = {**data, "request_id": str(uuid4()), "question": "Can you explain that?"}
    assert client.post(path, json=next_data).json()["state"] == "completed"
    assert (
        json.loads(provider.payload["messages"][1]["content"])["history"][0]["question"]
        == data["question"]
    )
    other = patient(client)
    assert client.get(f"/api/patients/{other['id']}/chat/{data['request_id']}").status_code == 404


def test_chat_requires_approved_current_context_and_correct_role(client):
    p, t, provider, data, _, _ = setup(client)
    path = f"/api/patients/{p['id']}/chat"
    assert client.post(path, json={**data, **REVIEWER}).status_code == 403
    assert client.post(path, json={**data, **CLINICIAN}).status_code == 403
    assert client.post(path, json={**data, "patient_revision": 2}).status_code == 409
    other = patient(client)
    other_path = f"/api/patients/{other['id']}/chat"
    assert client.get(other_path + "/context").json()["ready"] is False
    assert client.post(other_path, json=data).status_code == 409
    updated = deepcopy(p["body"])
    updated["facts"]["weight_kg"] = 65
    client.post(
        f"/api/patients/{p['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "body": updated,
        },
    )
    assert client.get(path + "/context").json()["ready"] is False
    assert client.post(path, json=data).status_code == 409
    assert provider.calls == 0


def test_chat_commits_pending_and_rechecks_context_after_provider(client):
    p, t, provider, data, _, _ = setup(client)
    path = f"/api/patients/{p['id']}/chat"

    def during():
        assert client.post(path, json=data).json()["state"] == "pending"
        updated = deepcopy(p["body"])
        updated["facts"]["weight_kg"] = 65
        assert (
            client.post(
                f"/api/patients/{p['id']}/revisions",
                json={
                    **CLINICIAN,
                    "expected_revision": 1,
                    "body": updated,
                },
            ).status_code
            == 201
        )

    provider.during_call = during
    run = client.post(path, json=data).json()
    assert run["state"] == "failed" and run["result"] is None
    assert "changed during generation" in run["error"]
    assert provider.calls == 1
    assert client.post(path, json=data).json() == run


def test_chat_rejects_invented_citations_and_retains_provider_failures(client):
    p, _, provider, data, _, _ = setup(client)
    path = f"/api/patients/{p['id']}/chat"
    provider.source_id = "invented"
    run = client.post(path, json=data).json()
    assert run["state"] == "failed" and run["result"] is None
    provider.error = "Provider returned HTTP 503"
    failed_data = {**data, "request_id": str(uuid4())}
    run = client.post(path, json=failed_data).json()
    assert run["state"] == "failed" and "503" in run["error"]
    assert client.post(path, json=failed_data).json() == run and provider.calls == 2


def test_chat_excludes_retired_evidence_and_keeps_abstention_flags(client):
    p, _, provider, data, evidence, _ = setup(client)
    assert (
        client.post(
            f"/api/evidence/rules/{evidence['id']}/retirement",
            json={
                **REVIEWER,
                "expected_revision": 1,
            },
        ).status_code
        == 200
    )
    rule(client, amount=40, subject="protein", unit="g/day")
    fresh = propose(client, p)
    assert approve(client, fresh).status_code == 200
    data.update(target_id=fresh["id"], target_revision=fresh["latest_revision"])

    def no_evidence(**payload):
        content = json.loads(payload["messages"][1]["content"])
        assert all(s["kind"] != "published_evidence" for s in content["sources"])
        return response(
            {
                "answer": "The sources do not provide a sodium recommendation.",
                "source_ids": [],
                "needs_clinician": False,
                "insufficient_evidence": True,
            }
        )

    provider.complete = no_evidence
    result = client.post(f"/api/patients/{p['id']}/chat", json=data).json()
    assert result["state"] == "completed" and result["result"]["insufficient_evidence"]


def workflow_setup(client):
    p, _, plan = setup_plan(client)
    provider = Provider()
    client.app.dependency_overrides[configured_client] = lambda: provider
    path = f"/api/patients/{p['id']}/chat"
    ctx = client.get(path + "/context").json()
    data = {
        **PATIENT,
        "request_id": str(uuid4()),
        "question": "Explain my plan and intake.",
        **{k: ctx[k] for k in ("patient_revision", "target_id", "target_revision")},
        "workflow": {"plan_id": plan["id"], "logged_on": "2026-11-01"},
    }
    return p, plan, provider, path, data


def test_chat_connects_plan_intake_and_calculated_comparisons(client):
    p, plan, provider, path, data = workflow_setup(client)
    entry = client.post(f"/api/patients/{p['id']}/meal-logs", json=planned(plan)).json()
    provider.source_id = "comparison:2026-11-01:0"
    run = client.post(path, json=data).json()
    assert run["state"] == "completed", run
    assert not run["stale"]
    sources = json.loads(provider.payload["messages"][1]["content"])["sources"]
    plan_source = next(s for s in sources if s["kind"] == "approved_plan")
    assert (
        json.loads(plan_source["text"])["daily_totals"]
        == plan["body"]["check"]["daily_totals"]["1"]
    )
    intake = json.loads(next(s["text"] for s in sources if s["id"] == "intake:2026-11-01"))
    assert not intake["complete"]
    assert any(item["status"] == "unlogged" for item in intake["planned_slots"])
    logged = json.loads(next(s["text"] for s in sources if s["id"].startswith("log:")))
    assert logged["nutrients"] == entry["body"]["nutrients"]
    assert logged["name"] == entry["body"]["consumed"]["food"]["name"]
    assert logged["nutrients"]["free_sugars"] is None
    comparison = json.loads(run["result"]["citations"][0]["quote"])
    assert comparison["status"] == "partial_day"
    corrected = client.post(
        f"/api/patients/{p['id']}/meal-logs/{entry['id']}/revisions",
        json={**planned(plan), "expected_revision": 1, "status": "skipped"},
    )
    assert corrected.status_code == 201
    historical = client.get(path + "/" + data["request_id"]).json()
    assert historical["stale"] and historical["result"] == run["result"]
    assert client.get(path).json()[0]["stale"]
    fresh = client.post(path, json={**data, "request_id": str(uuid4())}).json()
    assert fresh["state"] == "completed"
    assert json.loads(provider.payload["messages"][1]["content"])["history"] == []


def test_chat_rechecks_day_completeness_during_generation(client):
    p, _, provider, path, data = workflow_setup(client)
    provider.during_call = lambda: client.post(
        f"/api/patients/{p['id']}/meal-log-days/2026-11-01", json={**PATIENT, "complete": True}
    )
    run = client.post(path, json=data).json()
    assert run["state"] == "failed" and run["result"] is None
    assert "changed during generation" in run["error"]


def test_chat_rejects_foreign_unapproved_and_stale_plans_before_inference(client):
    _, plan, provider, path, data = workflow_setup(client)
    other, target = ready(client)
    foreign = request(client, target, [food(client, "foreign")])["alternatives"][0]
    assert approve_plan(client, foreign).status_code == 200
    assert (
        client.post(path, json={**data, "workflow": {"plan_id": foreign["id"]}}).status_code == 422
    )
    unapproved = next(
        row
        for row in client.get(f"/api/patients/{other['id']}/plans").json()
        if not row["approved_at"]
    )
    other_path = f"/api/patients/{other['id']}/chat"
    ctx = client.get(other_path + "/context").json()
    other_data = {
        **data,
        **{k: ctx[k] for k in ("patient_revision", "target_id", "target_revision")},
        "workflow": {"plan_id": unapproved["id"]},
    }
    assert client.post(other_path, json=other_data).status_code == 409
    original_food = plan["body"]["meals"][0]
    changed = client.get(f"/api/foods/{original_food['food_id']}").json()
    assert (
        client.post(
            f"/api/foods/{changed['id']}/revisions",
            json={
                **REVIEWER,
                "expected_revision": 1,
                "body": {**changed["body"], "name": "Changed food"},
            },
        ).status_code
        == 201
    )
    assert client.post(path, json=data).status_code == 409
    assert provider.calls == 0


def test_chat_substitutions_use_checked_candidates_and_do_not_modify_plans(client):
    p, target = ready(client)
    nutrients = {"energy": 330, "protein": 10, "carbohydrate": 50, "fat": 10, "sodium": 100}
    original = food(client, "original", nutrients=nutrients)
    replacement = food(client, "replacement", nutrients=nutrients, name="Checked replacement")
    plan = request(client, target, [original])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    provider = Provider()
    provider.source_id = "substitution:0"
    client.app.dependency_overrides[configured_client] = lambda: provider
    selection = {"day": 1, "slot": "lunch", "item": 1, "food_ids": [replacement["id"]]}
    path = f"/api/patients/{p['id']}/chat"
    data = {
        **PATIENT,
        "request_id": str(uuid4()),
        "question": "What can replace lunch?",
        "patient_revision": 1,
        "target_id": target["id"],
        "target_revision": target["latest_revision"],
        "workflow": {"plan_id": plan["id"], "substitution": selection},
    }
    before = client.get(f"/api/patients/{p['id']}/plans").json()
    run = client.post(path, json=data).json()
    assert run["state"] == "completed", run
    expected = client.post(
        f"/api/plans/{plan['id']}/substitution-recommendations", json={**PATIENT, **selection}
    ).json()
    suggestions = run["result"]["suggestions"]
    assert suggestions["recommendations"] == expected["recommendations"]
    assert suggestions["approval_required"]
    assert run["result"]["citations"][0]["kind"] == "checked_substitution"
    assert client.get(f"/api/patients/{p['id']}/plans").json() == before
    # Revision changes to a candidate outside the original plan still stale suggestions.
    assert (
        client.post(
            f"/api/foods/{replacement['id']}/revisions",
            json={
                **REVIEWER,
                "expected_revision": 1,
                "body": {**replacement["body"], "name": "Changed candidate"},
            },
        ).status_code
        == 201
    )
    assert client.get(path + "/" + data["request_id"]).json()["stale"]
    provider.source_id = "substitution-search"
    empty = client.post(
        path,
        json={
            **data,
            "request_id": str(uuid4()),
            "workflow": {
                "plan_id": plan["id"],
                "substitution": {**selection, "food_ids": [original["id"]]},
            },
        },
    ).json()
    assert empty["state"] == "completed"
    assert empty["result"]["suggestions"]["recommendations"] == []
    assert empty["result"]["suggestions"]["infeasibility_proven"] is False
    assert (
        client.post(
            path, json={**data, "request_id": str(uuid4()), "workflow": {"substitution": selection}}
        ).status_code
        == 422
    )
