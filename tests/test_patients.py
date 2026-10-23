import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient

from careloop.api import create_app
from careloop.patients.csv_import import COLUMNS

CLINICIAN = {"actor": {"name": "Test clinician", "role": "clinician"}, "reason": "Test decision"}
REVIEWER = {"actor": {"name": "Test reviewer", "role": "reviewer"}, "reason": "Test evidence"}


def patient(client, **facts):
    response = client.post(
        "/api/patients",
        json={
            **CLINICIAN,
            "body": {
                "display_name": "Test patient",
                "facts": {"age_years": 40, **facts},
                "provenance": {"kind": "manual", "source": "test://fixture", "notes": "Test only"},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def rule(
    client,
    *,
    amount=100,
    subject="sodium",
    unit="mg/day",
    applicability=None,
    exceptions=None,
    kind="ceiling",
):
    quote = "Illustrative test text only, not clinical guidance."
    source = client.post(
        "/api/evidence/sources",
        json={
            **REVIEWER,
            "title": "Test only",
            "locator": "test://fixture",
            "edition": "test",
            "content": quote,
        },
    ).json()
    body = {
        "source_id": source["id"],
        "quote": quote,
        "location": "test",
        "applicability": applicability or [],
        "exceptions": exceptions or [],
        "population_note": "Test population",
        "exception_note": "Test exceptions",
        "action": {
            "kind": kind,
            "subject": subject,
            "amount": amount,
            "unit": unit,
            "advice": "Test",
        },
    }
    response = client.post("/api/evidence/rules", json={**REVIEWER, "body": body})
    assert response.status_code == 201, response.text
    row = response.json()
    publish(client, row)
    return row, body


def publish(client, row):
    selected = [{"rule_id": row["id"], "revision": row["latest_revision"]}]
    response = client.post("/api/evidence/approvals", json={**REVIEWER, "rules": selected})
    assert response.status_code == 200, response.text
    generation = client.get("/api/evidence/catalogue").json()["generation"]
    response = client.post(
        "/api/evidence/publications",
        json={
            **REVIEWER,
            "rules": selected,
            "expected_generation": generation,
            "conflict_review": "Test review",
        },
    )
    assert response.status_code == 201, response.text


def propose(client, row):
    response = client.post(
        f"/api/patients/{row['id']}/targets",
        json={**CLINICIAN, "expected_patient_revision": row["latest_revision"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, target):
    return client.post(
        f"/api/targets/{target['id']}/approval",
        json={
            **CLINICIAN,
            "expected_revision": target["latest_revision"],
            "completeness_note": "Reviewed test targets",
        },
    )


def test_missing_facts_do_not_become_false_and_patient_changes_flag_targets(client):
    rule(client, exceptions=[{"fact": "pregnant", "operator": "eq", "value": True}])
    p = patient(client)
    initial = propose(client, p)
    assert initial["evaluation"][0]["status"] == "incomplete"
    assert initial["evaluation"][0]["missing"] == ["pregnant"]
    assert approve(client, initial).status_code == 409
    body = deepcopy(p["body"])
    body["facts"]["pregnant"] = False
    changed = client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 1, "body": body},
    )
    assert changed.status_code == 201
    assert client.get(f"/api/targets/{initial['id']}").json()["needs_review"] is True
    fresh = propose(client, changed.json())
    assert fresh["evaluation"][0]["status"] == "applicable"
    assert approve(client, fresh).status_code == 200
    assert client.get(f"/api/patients/{p['id']}/target-readiness").json()["targets_ready"] is True
    body["facts"]["allergies"] = ["egg"]
    client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 2, "body": body},
    )
    historical = client.get(f"/api/targets/{fresh['id']}").json()
    assert historical["approved_revision"] == 1
    assert historical["body"]["items"] == fresh["body"]["items"]
    assert historical["needs_review"] is True
    assert client.get(f"/api/patients/{p['id']}/target-readiness").json()["targets_ready"] is False
    assert len(client.get(f"/api/patients/{p['id']}").json()["revisions"]) == 3


def test_ckd_status_revisions_change_stage_rule_eligibility(client):
    rule(client, applicability=[{"fact": "ckd_stage", "operator": "eq", "value": "G4"}])
    p = patient(client)
    assert propose(client, p)["evaluation"][0]["status"] == "incomplete"
    body = deepcopy(p["body"])
    body["facts"]["has_ckd"] = False
    changed = client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 1, "body": body},
    )
    assert changed.status_code == 201
    evaluated = propose(client, changed.json())["evaluation"][0]
    assert evaluated["status"] == "not_applicable"
    assert evaluated["missing"] == []
    body["facts"]["ckd_stage"] = "G4"
    invalid = client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 2, "body": body},
    )
    assert invalid.status_code == 422
    body["facts"]["has_ckd"] = True
    changed = client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 2, "body": body},
    )
    assert changed.status_code == 201
    assert propose(client, changed.json())["evaluation"][0]["status"] == "applicable"


def test_per_kg_calculation_citation_and_target_supersession(client):
    r, _ = rule(client, amount=0.8, subject="protein", unit="g/kg/day")
    p = patient(client, weight_kg=50)
    target = propose(client, p)
    item = target["body"]["items"][0]
    assert item["action"]["amount"] == 40
    assert item["action"]["unit"] == "g/day"
    assert item["calculation"]["weight_kg"] == 50
    assert item["rule"]["rule_id"] == r["id"]
    assert item["citation"]["quote"]
    assert approve(client, target).status_code == 200
    next_target = propose(client, p)
    assert approve(client, next_target).status_code == 200
    old = client.get(f"/api/targets/{target['id']}").json()
    assert old["needs_review"] is True
    assert old["review_reasons"] == ["targets_superseded"]
    current = client.get(f"/api/patients/{p['id']}/target-readiness").json()
    assert current["approved_target"]["id"] == next_target["id"]


def test_competing_targets_require_explicit_clinician_resolution(client):
    a, _ = rule(client, amount=100)
    b, _ = rule(client, amount=200)
    target = propose(client, patient(client))
    assert approve(client, target).status_code == 409
    edited = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "manual": [
                {
                    "action": {
                        "kind": "ceiling",
                        "subject": "sodium",
                        "amount": 150,
                        "unit": "mg/day",
                        "advice": "Test manual target",
                    },
                    "rationale": "Clinician-authored test override",
                }
            ],
            "dispositions": [
                {
                    "rule": {"rule_id": r["id"], "revision": 1},
                    "reason": "Replaced by explicit clinician target",
                }
                for r in (a, b)
            ],
        },
    )
    assert edited.status_code == 201, edited.text
    item = edited.json()["body"]["items"][0]
    assert item["origin"] == "clinician" and "citation" not in item and "rule" not in item
    assert item["author"] == "Test clinician"
    assert approve(client, edited.json()).status_code == 200
    assert approve(client, target).status_code == 409


def test_newly_applicable_publication_and_retirement_flag_targets(client):
    r, body = rule(client, applicability=[{"fact": "age_years", "operator": "gte", "value": 60}])
    p = patient(client)
    original = propose(client, p)
    assert original["evaluation"][0]["status"] == "not_applicable"
    body["applicability"][0]["value"] = 18
    revision = client.post(
        f"/api/evidence/rules/{r['id']}/revisions",
        json={**REVIEWER, "expected_revision": 1, "body": body},
    ).json()
    assert client.get(f"/api/targets/{original['id']}").json()["needs_review"] is False
    publish(client, revision)
    assert client.get(f"/api/targets/{original['id']}").json()["needs_review"] is True
    fresh = propose(client, p)
    assert approve(client, fresh).status_code == 200
    response = client.post(
        f"/api/evidence/rules/{r['id']}/retirement", json={**REVIEWER, "expected_revision": 2}
    )
    assert response.status_code == 200
    assert client.get(f"/api/targets/{fresh['id']}").json()["needs_review"] is True
    assert propose(client, p)["evaluation"] == []
    events = client.get("/api/audit", params={"entity_id": fresh["id"]}).json()
    assert events[-1]["action"] == "targets.flagged"


def test_irrelevant_publication_does_not_invalidate_and_patient_audit_not_evidence_change(client):
    rule(client)
    before = client.get("/api/evidence/catalogue").json()["generation"]
    p = patient(client)
    target = propose(client, p)
    assert approve(client, target).status_code == 200
    assert client.get("/api/evidence/catalogue").json()["generation"] == before
    rule(client, applicability=[{"fact": "age_years", "operator": "gte", "value": 60}])
    assert client.get(f"/api/targets/{target['id']}").json()["needs_review"] is False


def csv_content(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    for external_id, age in rows:
        writer.writerow(
            {
                "display_name": "Imported test",
                "external_namespace": "test",
                "external_id": external_id,
                "facts_json": json.dumps({"age_years": age}),
                "provenance_json": json.dumps(
                    {"kind": "csv", "source": "test://csv", "notes": "Test"}
                ),
            }
        )
    return output.getvalue()


def test_csv_validation_duplicate_rollback_and_demo_role_gates(client):
    def send(rows):
        return client.post(
            "/api/patients/import-csv", json={**CLINICIAN, "content": csv_content(rows)}
        )

    assert send([("1", 30), ("2", 1)]).status_code == 422
    assert client.get("/api/patients").json() == []
    assert send([("1", 30)]).status_code == 201
    assert send([("2", 20), ("1", 30)]).status_code == 409
    assert len(client.get("/api/patients").json()) == 1
    assert send([("3", 30), ("3", 30)]).status_code == 422
    denied = client.post(
        "/api/patients/import-csv", json={**REVIEWER, "content": csv_content([("4", 30)])}
    )
    assert denied.status_code == 403


def test_concurrent_patient_change_and_target_approval_cannot_leave_ready_stale_target(
    client, database
):
    rule(client)
    p = patient(client)
    target = propose(client, p)

    def update_or_approve(update):
        with TestClient(create_app(database)) as other:
            if update:
                body = deepcopy(p["body"])
                body["facts"]["weight_kg"] = 55
                return other.post(
                    f"/api/patients/{p['id']}/revisions",
                    json={**CLINICIAN, "expected_revision": 1, "body": body},
                ).status_code
            return approve(other, target).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = list(executor.map(update_or_approve, [True, False]))
    assert codes[0] == 201 and codes[1] in (200, 409)
    assert client.get(f"/api/patients/{p['id']}/target-readiness").json()["targets_ready"] is False


def test_missing_facts_cannot_be_dismissed_as_manual_completion(client):
    r, _ = rule(client, applicability=[{"fact": "egfr", "operator": "lte", "value": 60}])
    target = propose(client, patient(client))
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "manual": [],
            "dispositions": [
                {"rule": {"rule_id": r["id"], "revision": 1}, "reason": "Ignore unknown lab"}
            ],
        },
    )
    assert response.status_code == 422
    assert approve(client, target).status_code == 409


def test_new_rule_flags_manual_target_and_unknown_age_blocks_approval(client):
    p = patient(client)
    target = propose(client, p)
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "dispositions": [],
            "manual": [
                {
                    "action": {
                        "kind": "ceiling",
                        "subject": "sodium",
                        "amount": 100,
                        "unit": "mg/day",
                        "advice": "Test only",
                    },
                    "rationale": "Explicit clinician completion",
                }
            ],
        },
    )
    assert response.status_code == 201
    assert approve(client, response.json()).status_code == 200
    rule(client)
    assert client.get(f"/api/targets/{target['id']}").json()["needs_review"] is True
    unknown = propose(client, patient(client, age_years=None))
    assert approve(client, unknown).status_code == 409
    dialysis = propose(client, patient(client, dialysis=True))
    assert approve(client, dialysis).status_code == 409


def test_qualitative_assessment_requires_clinician_disposition(client):
    r, _ = rule(client, kind="assessment", subject="review", amount=None, unit=None)
    target = propose(client, patient(client))
    assert target["evaluation"][0]["status"] == "needs_clinician"
    assert target["body"]["items"] == []
    assert approve(client, target).status_code == 409
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "dispositions": [
                {
                    "rule": {"rule_id": r["id"], "revision": 1},
                    "reason": "Test assessment completed by clinician",
                }
            ],
            "manual": [
                {
                    "action": {
                        "kind": "intake",
                        "subject": "protein",
                        "amount": 50,
                        "unit": "g/day",
                        "advice": "Test only",
                    },
                    "rationale": "Clinician-authored after assessment",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert approve(client, response.json()).status_code == 200
