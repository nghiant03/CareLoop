from copy import deepcopy

from test_evidence import DECISION, draft, publication, selection

from careloop.evidence.conflicts import overlap


def population(*conditions, exceptions=None):
    return {"applicability": list(conditions), "exceptions": exceptions or []}


def condition(fact, operator, value):
    return {"fact": fact, "operator": operator, "value": value}


def test_population_overlap_inclusive_edges_exceptions_and_unknowns():
    adults = population(condition("age_years", "gte", 18))
    assert overlap(adults, population(condition("age_years", "lte", 18))) is True
    assert overlap(adults, population(condition("age_years", "lte", 17))) is False
    excluding_adults = population(exceptions=[condition("age_years", "gte", 18)])
    assert overlap(adults, excluding_adults) is False
    assert (
        overlap(
            population(condition("pregnant", "eq", True)),
            population(exceptions=[condition("pregnant", "eq", True)]),
        )
        is False
    )
    assert (
        overlap(
            population(condition("conditions", "contains", "hypertension")),
            population(condition("conditions", "contains", "ckd")),
        )
        is True
    )
    assert overlap(adults, population(condition("unknown_fact", "eq", "x"))) is None


def test_incompatible_numeric_publication_block_and_population_resolution(client):
    first, body = draft(client)
    second_body = deepcopy(body)
    second_body["action"] = {
        "kind": "range",
        "subject": "test_nutrient",
        "amount": 120,
        "upper": 150,
        "unit": "mg/day",
        "advice": "Test only",
    }
    second = client.post("/api/evidence/rules", json={**DECISION, "body": second_body}).json()
    chosen = {**DECISION, "rules": [*selection(first)["rules"], *selection(second)["rules"]]}
    assert client.post("/api/evidence/approvals", json=chosen).status_code == 200
    report = client.post("/api/evidence/conflict-check", json=chosen)
    assert report.status_code == 200, report.text
    assert len(report.json()["blocking_conflicts"]) == 1
    assert (
        client.post("/api/evidence/publications", json=publication(client, chosen)).status_code
        == 409
    )
    assert client.get("/api/evidence/publications").json() == []
    second_body["applicability"] = [condition("age_years", "lte", 17)]
    edited = client.post(
        f"/api/evidence/rules/{second['id']}/revisions",
        json={**DECISION, "expected_revision": 1, "body": second_body},
    )
    assert edited.status_code == 201
    chosen["rules"][1]["revision"] = 2
    assert client.post("/api/evidence/approvals", json=chosen).status_code == 200
    assert (
        client.post("/api/evidence/publications", json=publication(client, chosen)).status_code
        == 201
    )


def test_selection_checked_against_active_rules_and_different_units_need_review(client):
    first, body = draft(client)
    chosen = selection(first)
    assert client.post("/api/evidence/approvals", json=chosen).status_code == 200
    assert (
        client.post("/api/evidence/publications", json=publication(client, chosen)).status_code
        == 201
    )
    body["action"] = {
        "kind": "range",
        "subject": "test_nutrient",
        "amount": 120,
        "upper": 150,
        "unit": "g/day",
        "advice": "Test only",
    }
    second = client.post("/api/evidence/rules", json={**DECISION, "body": body}).json()
    report = client.post("/api/evidence/conflict-check", json=selection(second)).json()
    assert not report["blocking_conflicts"]
    assert len(report["review_findings"]) == 1
    assert report["manual_review_required"]
    found = client.get("/api/evidence/passages", params={"q": "illustrative"}).json()
    assert found
    client.post(
        f"/api/evidence/rules/{first['id']}/retirement", json={**DECISION, "expected_revision": 1}
    )
    assert not client.get("/api/evidence/passages", params={"q": "illustrative"}).json()
