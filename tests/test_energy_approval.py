from test_patients import CLINICIAN, approve, patient, propose, rule, with_energy

from careloop.patients import service


def test_energy_note_and_estimate_do_not_substitute_for_numeric_target(client, monkeypatch):
    rule(client)
    assessment, _ = rule(client, kind="assessment", subject="energy", amount=None, unit=None)
    p = patient(
        client, weight_kg=78, height_cm=170, pregnant=False, breastfeeding=False, dialysis=False
    )
    target = propose(client, p)
    assert target["body"]["energy_proposal"]["action"]
    edited = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [i["rule"] for i in target["body"]["items"]],
            "dispositions": [
                {"rule": {"rule_id": assessment["id"], "revision": 1}, "reason": "2000"}
            ],
            "manual": [],
        },
    )
    assert edited.status_code == 201
    target = edited.json()
    assert "daily energy range" in str(target["body"]["blockers"])
    rejected = approve(client, target)
    assert rejected.status_code == 409
    assert "assessment note" in rejected.text

    # Reproduce a historical approval made before the energy requirement was checked.
    with monkeypatch.context() as old:
        old.setattr(service, "energy_target_issue", lambda items: None)
        assert approve(client, target).status_code == 200
    ready = client.get(f"/api/patients/{p['id']}/target-readiness").json()
    assert not ready["targets_ready"]
    assert "approved targets have no daily energy range" in ready["reason"]
    assert client.get(f"/api/targets/{target['id']}").json()["approved_revision"] == 2


def test_saved_energy_range_allows_approval_and_readiness(client):
    rule(client)
    p = patient(client)
    target = with_energy(client, propose(client, p))
    assert target["body"]["blockers"] == []
    assert approve(client, target).status_code == 200
    assert client.get(f"/api/patients/{p['id']}/target-readiness").json()["targets_ready"]
