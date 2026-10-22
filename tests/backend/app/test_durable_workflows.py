import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.core import persistence
from backend.app.core.approval_gate import get_envelope
from backend.app.core.plan_service import map_plan_result
from backend.app.main import app
from backend.mining.patient_swaps import plan_from_document
from backend.optim.problem import evaluate
from backend.optim.real_data import load_dishes


@pytest.fixture
def api(pg_databases, monkeypatch):
    monkeypatch.setenv("CARELOOP_APP_DATABASE_URL", pg_databases["clinical"])
    with TestClient(app) as client:
        yield client


def approve(api, pid="P0001"):
    response = api.post("/rules/run", json={"patient_id": pid})
    assert response.status_code == 200, response.text
    eid = response.json()["envelope"]["envelope_id"]
    response = api.post(f"/envelopes/{eid}/approve", json={})
    assert response.status_code == 200
    return response.json()


def test_real_restart_restores_approval_and_mints_fresh_identity(api):
    envelope = approve(api)
    original = envelope["envelope_id"]
    assert api.post("/adherence/log", json={"patient_id": "P0001", "date": datetime.now(UTC).date().isoformat(),
                                           "meal": "lunch", "dish_id": "SG0001"}).status_code == 201
    script = '''
import json
from fastapi.testclient import TestClient
from backend.app.main import app
with TestClient(app) as c:
    old=c.get('/envelopes/latest',params={'patient_id':'P0001'})
    adherence=c.get('/adherence/P0001/summary')
    new=c.post('/rules/run',json={'patient_id':'P0001'})
    print(json.dumps({'old':old.json(), 'adherence':adherence.status_code,'new':new.json()}))
'''
    completed = subprocess.run([sys.executable, "-c", script], check=True, text=True, capture_output=True, env=os.environ.copy())
    output = json.loads(completed.stdout)
    assert output["old"]["status"] == "APPROVED"
    assert output["old"]["targets"] == envelope["targets"]
    assert output["adherence"] == 200
    assert output["new"]["envelope"]["envelope_id"] != original
    assert api.get("/envelopes/latest", params={"patient_id": "P0001"}).json()["status"] == "PROPOSED"


def test_observation_drives_rules_and_review_without_changing_approval(api):
    old = approve(api)
    r = api.post("/observations", json={"patient_id": "P0001", "metric": "serum_K_meq_L",
                                      "value": 6.5, "unit": "mEq/L"})
    assert r.status_code == 201, r.text
    assert api.get("/patients/P0001").json()["serum_K_meq_L"] == 6.5

    egfr = api.post("/observations", json={"patient_id": "P0001", "metric": "egfr", "value": 42,
                                          "unit": "mL/min/1.73m²"})
    assert egfr.status_code == 201, egfr.text
    assert api.get("/patients/P0001").json()["egfr"] == 42
    assert api.get(f"/envelopes/{old['envelope_id']}").json()["status"] == "APPROVED"
    items = api.get("/review/queue", params={"patient_id": "P0001"}).json()["items"]
    lab = next(i for i in items if i["source"] == "lab_trend" and i["kind"] == "K")
    assert lab["severity"] == "alert"
    proposal = api.post(f"/review/{lab['review_id']}/proposal").json()
    envelope = api.get(f"/envelopes/{proposal['envelope_id']}").json()
    assert envelope["status"] == "PROPOSED"
    assert any(t["nutrient"] == "potassium_mg" and t["kind"] == "max" for t in envelope["targets"])
    api.post("/observations", json={"patient_id": "P0001", "metric": "serum_K_meq_L", "value": 4.,
                                   "unit": "mEq/L", "observed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat()})
    assert api.get("/patients/P0001").json()["serum_K_meq_L"] == 6.5


def test_incomplete_days_do_not_generate_trend_alerts(api):
    approve(api)
    for offset, dish in zip((-2, -1, 0), ("SG0207", "SG0204", "SG0001")):
        api.post("/adherence/log", json={"patient_id": "P0001", "date": (datetime.now(UTC).date() + timedelta(days=offset)).isoformat(),
                                        "meal": "lunch", "dish_id": dish})
    deviation = api.get("/adherence/P0001/deviation").json()
    assert deviation["flags"] == []
    assert all(not point["complete"] for series in deviation["series"].values() for point in series["points"])
    items = api.get("/review/queue", params={"patient_id": "P0001"}).json()["items"]
    assert not any(i["source"] == "adherence_flag" for i in items)


def test_plan_meets_energy_and_fibre_floors_and_is_loggable(api):
    e = approve(api)
    plan = api.post("/plans", json={"patient_id": "P0001"}).json()
    assert plan["meal_complete"] and plan["hard_feasible"]
    assert plan["source_hashes"]["data/dishes.json"]
    assert plan["approved_envelope"]["envelope_id"] == e["envelope_id"]
    envelope = get_envelope(e["envelope_id"])
    assert envelope is not None
    _, violations = evaluate(plan_from_document(plan), envelope, load_dishes())
    assert not violations
    for row in plan["adequacy"]:
        if row["kind"] == "min" and row["nutrient"] in ("energy_kcal", "fiber_g"):
            assert row["met_days"] == 7
    day = plan["days"][0]
    for meal in ("breakfast", "lunch", "dinner"):
        r = api.post("/adherence/log", json={"patient_id": "P0001", "date": datetime.now(UTC).date().isoformat(), "meal": meal,
            "items": [{"dish_id": slot["dish_id"], "quantity": 1} for slot in day["slots"] if slot["meal"] == meal]})
        assert r.status_code == 201, r.text
    logged = api.get("/adherence/P0001/summary").json()["days"][0]
    assert logged["completeness"]["complete"]
    assert logged["compliant"]
    for total in day["totals"]:
        assert logged["totals"][total["nutrient"]] == pytest.approx(total["value"])


def test_saved_plan_swap_preview_uses_requested_plan(api):
    e = approve(api)
    old = api.post("/plans", json={"patient_id": "P0001"}).json()
    source = old["days"][0]["slots"][0]["dish_id"]
    newer = deepcopy(old)
    for day in newer["days"]:
        day["slots"] = [slot for slot in day["slots"] if slot["dish_id"] != source]
    persistence.save_plan("P0001", e["envelope_id"], 1, "test", True, 0, document=newer)
    query = {"patient_id": "P0001", "dish_id": source}
    assert api.get("/mining/substitutions", params=query).status_code == 409
    r = api.get("/mining/substitutions", params={**query, "plan_id": old["plan_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["plan_id"] == old["plan_id"]
    assert r.json()["affected_days"]


def test_mapper_preserves_exact_diagnosis(api):
    e = approve(api)
    diagnosis = {"feasible": False, "infeasibility_status": "search_exhausted",
                 "exact_reference": {"feasible_day": True, "feasible_combo_count": 1, "pool_size": 3}}
    envelope = get_envelope(e["envelope_id"])
    assert envelope is not None
    mapped = map_plan_result(diagnosis, envelope, load_dishes())
    assert mapped["infeasibility_status"] == "search_exhausted"
    assert mapped["exact_reference"] == diagnosis["exact_reference"]


def test_multi_item_quantities_and_validation(api):
    approve(api)
    payload = {"patient_id": "P0001", "date": datetime.now(UTC).date().isoformat(), "meal": "lunch",
               "items": [{"dish_id": "SG0001", "quantity": .5}, {"dish_id": "SG0204", "quantity": 2}]}
    assert api.post("/adherence/log", json=payload).status_code == 201
    total = api.get("/adherence/P0001/summary").json()["days"][0]["totals"]["energy_kcal"]
    lookup = {d.dish_id: d for d in load_dishes()}
    assert total == pytest.approx(.5 * lookup["SG0001"].nutrient("energy_kcal") + 2 * lookup["SG0204"].nutrient("energy_kcal"))
    assert api.post("/adherence/log", json={**payload, "dish_id": "SG0001"}).status_code == 422
    assert api.post("/adherence/log", json={**payload, "items": []}).status_code == 422


def test_constraint_provenance_survives_edit_and_durable_reread(api):
    e = approve(api)
    targets = e["targets"]
    for t in targets:
        if t["nutrient"] == "sodium_mg":
            t["value"] = 1800
    r = api.post(f"/envelopes/{e['envelope_id']}/edit", json={"targets": targets, "edited_by": "dr-test"})
    assert r.status_code == 200, r.text
    saved = get_envelope(e["envelope_id"])
    assert saved is not None
    sodium = next(t for t in saved.targets if t.nutrient.value == "sodium_mg")
    assert sodium.provenance is not None
    assert sodium.provenance.value == 1800
    assert sodium.provenance.author == "dr-test"
    assert sodium.provenance.version == saved.version
    assert sodium.provenance.citation is not None
    assert sodium.provenance.citation.rule_id == "CLINICIAN-EDIT"


def test_uncovered_history_not_scored_against_current_proposal(api):
    old = approve(api)
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    api.post("/adherence/log", json={"patient_id": "P0001", "date": yesterday, "meal": "lunch", "dish_id": "SG0001"})
    api.post("/rules/run", json={"patient_id": "P0001"})
    summary = api.get("/adherence/P0001/summary").json()
    assert summary["unattributed_days"] == [yesterday]
    assert summary["days"] == []
    effective = persistence.envelope_effective_at("P0001", datetime.now(UTC).date().isoformat())
    assert effective is not None
    assert effective.envelope_id == old["envelope_id"]
