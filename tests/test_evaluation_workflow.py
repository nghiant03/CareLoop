"""Integrated acceptance scenario using existing explicit software-test fixtures."""

from uuid import uuid4

from test_inference import response
from test_logging import planned
from test_patients import CLINICIAN, REVIEWER
from test_planning import PATIENT, approve_plan, food, ready, request

from careloop.inference import Settings, configured_client


def test_plan_substitution_intake_chat_and_reassessment_lifecycle(client):
    patient, target = ready(client)
    nutrients = {"energy": 330, "protein": 10, "carbohydrate": 50, "fat": 10, "sodium": 100}
    original = food(client, "workflow-original", nutrients=nutrients)
    replacement = food(client, "workflow-replacement", nutrients=nutrients)
    plans = request(client, target, [original])["alternatives"]
    assert len(plans) == 3
    parent = plans[0]
    assert approve_plan(client, parent).status_code == 200
    assert approve_plan(client, plans[1]).status_code == 409
    recommendations = client.post(
        f"/api/plans/{parent['id']}/substitution-recommendations",
        json={**PATIENT, "day": 1, "slot": "lunch", "food_ids": [replacement["id"]]},
    )
    assert recommendations.status_code == 200
    selection = recommendations.json()["recommendations"][0]["substitution"]
    draft_response = client.post(
        f"/api/plans/{parent['id']}/substitutions", json={**PATIENT, **selection}
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["approved_at"] is None
    assert approve_plan(client, draft).status_code == 200
    assert client.get(f"/api/plans/{parent['id']}").json()["needs_review"]
    base = f"/api/patients/{patient['id']}"
    assert client.post(base + "/meal-logs", json=planned(draft)).status_code == 201

    class Provider:
        settings = Settings("https://test.example/v1/", "test-only")
        calls = 0

        def complete(self, **payload):
            self.calls += 1
            return response(
                {
                    "answer": "The recorded energy range is 900–1200 kcal/day.",
                    "source_ids": ["approved-targets"],
                    "needs_clinician": False,
                    "insufficient_evidence": False,
                }
            )

    provider = Provider()
    client.app.dependency_overrides[configured_client] = lambda: provider
    data = {
        **PATIENT,
        "request_id": str(uuid4()),
        "question": "Explain the approved target.",
        "patient_revision": 1,
        "target_id": target["id"],
        "target_revision": target["latest_revision"],
        "workflow": {"plan_id": draft["id"], "logged_on": "2026-11-01"},
    }
    run = client.post(base + "/chat", json=data).json()
    assert run["state"] == "completed" and not run["stale"]
    assert client.post(base + "/chat", json=data).json()["id"] == run["id"]
    assert provider.calls == 1
    revised = client.post(
        f"/api/foods/{replacement['id']}/revisions",
        json={
            **REVIEWER,
            "expected_revision": 1,
            "body": {**replacement["body"], "nutrients": {**nutrients, "sodium": 9999}},
        },
    )
    assert revised.status_code == 201
    assert client.get(base + "/chat/" + run["id"]).json()["stale"]
    assert client.get(f"/api/plans/{draft['id']}").json()["needs_review"]
    assert (
        client.post(
            f"/api/plans/{draft['id']}/substitutions", json={**PATIENT, **selection}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/plans/{draft['id']}/approval",
            json={**CLINICIAN, "review_note": "Must not approve stale plan"},
        ).status_code
        == 409
    )
    assert client.get(base + "/meal-log-days/2026-11-01").json()["entries"]
