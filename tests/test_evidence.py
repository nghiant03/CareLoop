from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from careloop.api import create_app
from careloop.db import migrate
from careloop.evidence.models import Action

DECISION = {"actor": {"name": "Demo reviewer", "role": "reviewer"}, "reason": "Test review"}
# Test-only invented text; no clinical guideline or demo data is seeded by the application.
TEXT = "Example test population: an illustrative ceiling is 100 mg per day."


def draft(client, *, blockers=None):
    response = client.post(
        "/api/evidence/sources",
        json={
            **DECISION,
            "title": "Test-only source",
            "edition": "test",
            "locator": "test://fixture",
            "content": TEXT,
        },
    )
    assert response.status_code == 201, response.text
    body = {
        "source_id": response.json()["id"],
        "quote": TEXT,
        "location": "paragraph 1",
        "applicability": [{"fact": "age_years", "operator": "gte", "value": 18}],
        "population_note": "Test adults",
        "exceptions": [],
        "exception_note": "Test only",
        "action": {
            "kind": "ceiling",
            "subject": "test_nutrient",
            "amount": 100,
            "unit": "mg/day",
            "advice": "Test ceiling",
        },
        "blockers": blockers or [],
    }
    response = client.post("/api/evidence/rules", json={**DECISION, "body": body})
    assert response.status_code == 201, response.text
    return response.json(), body


def selection(rule, revision=1):
    return {**DECISION, "rules": [{"rule_id": rule["id"], "revision": revision}]}


def publication(client, selected):
    generation = client.get("/api/evidence/catalogue").json()["generation"]
    return {
        **selected,
        "expected_generation": generation,
        "conflict_review": "Reviewed test catalogue; no unresolved conflicts in selection",
    }


def test_review_publication_revision_retirement_and_history(client):
    rule, body = draft(client)
    selected = selection(rule)
    assert (
        client.post("/api/evidence/publications", json=publication(client, selected)).status_code
        == 409
    )
    assert client.post("/api/evidence/approvals", json=selected).status_code == 200
    assert client.get(f"/api/evidence/rules/{rule['id']}").json()["active_revision"] is None
    assert (
        client.post("/api/evidence/publications", json=publication(client, selected)).status_code
        == 201
    )
    body["action"]["amount"] = 90
    revised = client.post(
        f"/api/evidence/rules/{rule['id']}/revisions",
        json={
            **DECISION,
            "body": body,
            "expected_revision": 1,
        },
    )
    assert revised.status_code == 201
    assert revised.json()["active_revision"] == 1
    assert revised.json()["revisions"][1]["approved_by"] is None
    assert revised.json()["revisions"][0]["body"]["action"]["amount"] == 100
    assert client.post("/api/evidence/approvals", json=selected).status_code == 409
    selected = selection(rule, 2)
    assert client.post("/api/evidence/approvals", json=selected).status_code == 200
    assert (
        client.post("/api/evidence/publications", json=publication(client, selected)).status_code
        == 201
    )
    retired = client.post(
        f"/api/evidence/rules/{rule['id']}/retirement",
        json={
            **DECISION,
            "expected_revision": 2,
        },
    )
    assert retired.status_code == 200
    assert retired.json()["retired"] is True
    assert retired.json()["active_revision"] == 2  # historical published pointer retained
    assert (
        client.post("/api/evidence/publications", json=publication(client, selected)).status_code
        == 409
    )
    assert len(client.get("/api/evidence/publications").json()) == 2
    events = client.get("/api/audit", params={"entity_id": rule["id"]}).json()
    assert [e["action"] for e in events] == [
        "rule.drafted",
        "rule.approved",
        "rule.drafted",
        "rule.approved",
        "rule.retired",
    ]
    catalogue = client.get("/api/evidence/catalogue").json()
    assert catalogue["rules"][0]["retired"] is True


def test_batch_is_atomic_and_selected_subset_can_be_approved(client):
    first, _ = draft(client)
    blocked, _ = draft(client, blockers=["Unresolved conflicting recommendation"])
    both = {**DECISION, "rules": [*selection(first)["rules"], *selection(blocked)["rules"]]}
    assert client.post("/api/evidence/approvals", json=both).status_code == 409
    assert (
        client.get(f"/api/evidence/rules/{first['id']}").json()["revisions"][0]["approved_by"]
        is None
    )
    assert client.post("/api/evidence/approvals", json=selection(first)).status_code == 200
    assert (
        client.post("/api/evidence/publications", json=publication(client, both)).status_code == 409
    )
    assert client.get(f"/api/evidence/rules/{first['id']}").json()["active_revision"] is None
    assert (
        client.post(
            "/api/evidence/publications", json=publication(client, selection(first))
        ).status_code
        == 201
    )


def test_stale_catalogue_review_cannot_publish(client):
    rule, _ = draft(client)
    selected = selection(rule)
    client.post("/api/evidence/approvals", json=selected)
    reviewed = publication(client, selected)
    draft(client)
    assert client.post("/api/evidence/publications", json=reviewed).status_code == 409
    assert client.get("/api/evidence/publications").json() == []


def test_quote_validation_and_role_gate_leave_no_audit_side_effects(client):
    rule, body = draft(client)
    before = client.get("/api/audit").json()
    body["quote"] = "Invented quote that is not in the source"
    assert client.post("/api/evidence/rules", json={**DECISION, "body": body}).status_code == 422
    selected = selection(rule)
    selected["actor"] = {"name": "Demo patient", "role": "patient"}
    assert client.post("/api/evidence/approvals", json=selected).status_code == 403
    assert client.get("/api/audit").json() == before


def test_concurrent_edits_only_one_succeeds(client, database):
    rule, body = draft(client)

    def edit(amount):
        edited = deepcopy(body)
        edited["action"]["amount"] = amount
        with TestClient(create_app(database)) as other:
            return other.post(
                f"/api/evidence/rules/{rule['id']}/revisions",
                json={
                    **DECISION,
                    "body": edited,
                    "expected_revision": 1,
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(edit, [80, 90])) == [201, 409]
    assert len(client.get(f"/api/evidence/rules/{rule['id']}").json()["revisions"]) == 2


def test_restart_and_migration_idempotency(client, database):
    rule, _ = draft(client)
    migrate(database)
    with TestClient(create_app(database)) as restarted:
        assert restarted.get("/api/health").status_code == 200
        assert restarted.get(f"/api/evidence/rules/{rule['id']}").json() == rule
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 6
        conn.execute("UPDATE schema_migrations SET checksum = 'tampered'")
    with pytest.raises(RuntimeError, match="Applied migration changed"):
        migrate(database)


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "ceiling", "subject": "x", "advice": "x"},
        {"kind": "assessment", "subject": "x", "advice": "x", "amount": 1, "unit": "g"},
        {"kind": "range", "subject": "x", "advice": "x", "amount": 10, "upper": 5, "unit": "g"},
        {"kind": "ceiling", "subject": "x", "advice": "x", "amount": float("nan"), "unit": "g"},
    ],
)
def test_invalid_numeric_guidance_is_rejected(action):
    with pytest.raises(ValidationError):
        Action.model_validate(action)


def test_empty_and_duplicate_selections_rejected(client):
    rule, _ = draft(client)
    selected = selection(rule)
    assert client.post("/api/evidence/approvals", json={**DECISION, "rules": []}).status_code == 422
    selected["rules"] *= 2
    assert client.post("/api/evidence/approvals", json=selected).status_code == 422
