import io
import json
import sys
import urllib.request

import pytest
from pydantic import ValidationError
from test_patients import CLINICIAN, REVIEWER, approve, patient, propose, publish, rule

from careloop.evidence.categorize_rules import main
from careloop.evidence.models import RuleBody
from careloop.patients.engine import evaluate_rule, target_blockers


def classified(client, role="required", applicability=None):
    row, body = rule(client, applicability=applicability)
    body.update(
        review_role=role,
        review_note="Reviewed source scope",
        action={"kind": "assessment", "subject": "protein", "advice": "Review source"},
    )
    response = client.post(
        f"/api/evidence/rules/{row['id']}/revisions",
        json={
            **REVIEWER,
            "expected_revision": 1,
            "body": body,
        },
    )
    assert response.status_code == 201, response.text
    row = response.json()
    publish(client, row)
    return row, body


def test_advisory_role_is_explicit_and_cannot_hide_numeric_constraints(client):
    _, body = classified(client, "advisory")
    with pytest.raises(ValidationError, match="Advisory guidance"):
        RuleBody.model_validate({**body, "review_note": None})
    with pytest.raises(ValidationError, match="Advisory guidance"):
        RuleBody.model_validate(
            {
                **body,
                "action": {
                    "kind": "minimum",
                    "subject": "protein",
                    "amount": 50,
                    "unit": "g/day",
                    "advice": "Test",
                },
            }
        )
    legacy = {k: v for k, v in body.items() if k not in {"review_role", "review_note"}}
    assert RuleBody.model_validate(legacy).review_role == "required"
    unsupported = evaluate_rule(
        {
            "rule_id": "timing",
            "revision": 1,
            "body": {
                **legacy,
                "action": {"kind": "timing", "subject": "carbohydrate", "advice": "Review timing"},
            },
        },
        {},
    )
    assert unsupported["category"] == "assessment"
    assert unsupported["status"] == "needs_clinician"


def test_advisory_unknown_applicability_is_not_a_blocker_or_selectable(client):
    row, body = classified(
        client,
        "advisory",
        [
            {"fact": "pregnant", "operator": "eq", "value": True},
        ],
    )
    evaluated = evaluate_rule({"rule_id": row["id"], "revision": 2, "body": body}, {})
    assert evaluated["status"] == "incomplete"
    assert not any(b.get("rule_id") for b in target_blockers([evaluated], [], []))
    p = patient(client)
    target = propose(client, p)
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "manual": [],
            "dispositions": [],
            "guidance": [{"rule_id": row["id"], "revision": 2}],
        },
    )
    assert response.status_code == 422


def test_selected_guidance_and_required_assessment_are_separate_from_constraints(client):
    advisory, _ = classified(client, "advisory")
    required, _ = classified(client)
    target = propose(client, patient(client))
    assert target["body"]["items"] == []
    assert [b.get("rule_id") for b in target["body"]["blockers"] if b.get("rule_id")] == [
        required["id"]
    ]
    payload = {
        **CLINICIAN,
        "expected_revision": 1,
        "selected": [],
        "dispositions": [],
        "guidance": [{"rule_id": advisory["id"], "revision": 2}],
        "assessments": [
            {
                "rule": {"rule_id": required["id"], "revision": 2},
                "reason": "Assessed individual needs and entered energy target",
            }
        ],
        "manual": [
            {
                "action": {
                    "kind": "range",
                    "subject": "energy",
                    "amount": 1800,
                    "upper": 2200,
                    "unit": "kcal/day",
                    "advice": "Test",
                },
                "rationale": "Individual assessment",
            }
        ],
    }
    response = client.post(f"/api/targets/{target['id']}/revisions", json=payload)
    assert response.status_code == 201, response.text
    edited = response.json()
    assert not edited["body"]["blockers"]
    assert len(edited["body"]["items"]) == 1
    assert edited["body"]["guidance"][0]["citation"]
    assert edited["body"]["assessments"][0]["author"] == CLINICIAN["actor"]["name"]
    assert approve(client, edited).status_code == 200
    context = client.get(f"/api/patients/{edited['patient_id']}/chat/context").json()
    assert len(context["guidance"]) == 1
    assert len(context["target_items"]) == 1


def test_required_assessment_requires_nonempty_decision_and_unique_reference(client):
    required, _ = classified(client)
    target = propose(client, patient(client))
    ref = {"rule_id": required["id"], "revision": 2}
    payload = {
        **CLINICIAN,
        "expected_revision": 1,
        "selected": [],
        "dispositions": [],
        "manual": [],
        "assessments": [{"rule": ref, "reason": " "}],
    }
    assert client.post(f"/api/targets/{target['id']}/revisions", json=payload).status_code == 422
    payload["assessments"][0]["reason"] = "Completed"
    payload["dispositions"] = [{"rule": ref, "reason": "Declined"}]
    assert client.post(f"/api/targets/{target['id']}/revisions", json=payload).status_code == 422


def test_reviewed_classification_publication_is_idempotent(client, monkeypatch, tmp_path):
    row, before = classified(client)
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            [
                {
                    "rule_id": row["id"],
                    "revision": 2,
                    "before": before,
                    "body": {
                        **before,
                        "review_role": "advisory",
                        "review_note": "Source is counselling",
                    },
                    "reason": "Reviewed source as counselling rather than mandatory assessment",
                }
            ]
        )
    )

    def urlopen(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        route = url.removeprefix("http://testserver")
        response = (
            client.get(route)
            if isinstance(request, str) or request.data is None
            else client.post(route, json=json.loads(request.data))
        )
        assert response.status_code < 300, response.text
        return io.BytesIO(response.content)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        ["categories", "--review", str(path), "--api", "http://testserver/api", "--apply"],
    )
    main()
    after = client.get("/api/evidence/catalogue").json()
    published = next(r for r in after["rules"] if r["id"] == row["id"])
    assert published["active_revision"] == 3
    assert published["published"]["review_role"] == "advisory"
    main()
    assert client.get("/api/evidence/catalogue").json() == after
