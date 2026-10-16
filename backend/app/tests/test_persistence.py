"""Check durable workflow records through fresh SQLite handles and HTTP clients."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.adherence import store
from backend.app.core import persistence
from backend.app.main import app
from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)



def _run_rules(client, patient_id: str) -> dict:
    resp = client.post("/rules/run", json={"patient_id": patient_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _hand_envelope(
    patient_id: str,
    envelope_id: str,
    status: EnvelopeStatus = EnvelopeStatus.PROPOSED,
    sodium_max: float = 2000.0,
) -> NutrientEnvelope:
    return NutrientEnvelope(
        envelope_id=envelope_id,
        patient_id=patient_id,
        status=status,
        patient_snapshot=PatientSummary(
            patient_id=patient_id, age=60, sex="M", weight_kg=70.0
        ),
        targets=[
            NutrientConstraint(
                nutrient=NutrientKind.SODIUM_MG,
                kind=ConstraintKind.MAX,
                value=sodium_max,
                unit="mg",
            )
        ],
        priority_basis="test fixture: persistence journal",
    )


def _today(offset_days: int = 0) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset_days)).isoformat()


def test_plan_save_and_fresh_handle_roundtrip() -> None:
    patient_id = "P9999"
    document = {
        "patient_id": patient_id,
        "envelope_id": "ENV-P9999-001",
        "feasible": True,
        "engine": "test-engine",
        "violation_count": 0,
        "objectives": [{"nutrient": "sodium_mg", "kind": "max", "value": 2000.0}],
        "days": [{"day": 1, "slots": [], "totals": []}],
        "adequacy": [],
        "explanation": {"why": ["test"]},
    }
    plan_id = persistence.save_plan(
        patient_id=patient_id,
        envelope_id="ENV-P9999-001",
        envelope_version=3,
        engine="test-engine",
        feasible=True,
        violation_count=0,
        objectives=document["objectives"],
        days=document["days"],
        adequacy=document["adequacy"],
        kb_version="kb-test-1",
        document=document,
    )
    assert plan_id.startswith("PLAN-P9999-")

    stored = persistence.get_plan(plan_id)
    assert stored is not None
    assert stored["plan_id"] == plan_id
    assert stored["saved_at"]
    # identical document round-trip (plan_id/saved_at are the storage overlay)
    assert {k: v for k, v in stored.items() if k not in ("plan_id", "saved_at")} == document

    # A fresh transaction reads the same durable row.
    with persistence._connect() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    assert row is not None
    assert row["envelope_id"] == "ENV-P9999-001"
    assert row["envelope_version"] == 3
    assert row["kb_version"] == "kb-test-1"
    assert json.loads(row["document_json"]) == document

    # IDs advance while earlier rows remain stored.
    second = persistence.save_plan(
        patient_id=patient_id,
        envelope_id="ENV-P9999-001",
        envelope_version=3,
        engine="test-engine",
        feasible=False,
        violation_count=1,
    )
    assert second != plan_id and second.startswith("PLAN-P9999-")

    summaries = persistence.list_plans(patient_id)
    assert [s["plan_id"] for s in summaries] == [second, plan_id]  # newest first
    assert summaries[0]["feasible"] is False
    assert summaries[0]["violation_count"] == 1
    latest = persistence.latest_plan_for_patient(patient_id)
    assert latest is not None and latest["plan_id"] == second
    assert persistence.latest_plan_for_patient("NO-SUCH-PATIENT") is None


def test_plans_api_list_get_and_restart(client) -> None:
    # full wired flow: rules -> approve -> POST /plans
    body = _run_rules(client, "P0001")
    envelope = body["envelope"]
    approved = client.post(
        f"/envelopes/{envelope['envelope_id']}/approve",
        json={"clinician_id": "dr-tan", "note": "persistence e2e"},
    )
    assert approved.status_code == 200, approved.text

    plan_resp = client.post("/plans", json={"patient_id": "P0001"})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    plan_id = plan["plan_id"]
    assert plan_id.startswith("PLAN-P0001-")
    assert plan["saved_at"]
    # the ORIGINAL approved envelope's id/version is persisted
    assert plan["envelope_id"] == envelope["envelope_id"]

    # list summaries through the API
    listed = client.get("/plans", params={"patient_id": "P0001"})
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["count"] >= 1
    ids = [row["plan_id"] for row in payload["plans"]]
    assert plan_id in ids
    assert all(set(row) >= {"plan_id", "patient_id", "envelope_id", "created_at"}
               for row in payload["plans"])

    # A new client lifespan reads the plan from PostgreSQL.
    with TestClient(app) as fresh_client:
        reread = fresh_client.get(f"/plans/{plan_id}")
    assert reread.status_code == 200, reread.text
    assert reread.json() == plan  # identical document after client recreation

    # unknown plan id -> documented 404 body
    missing = client.get("/plans/PLAN-P0001-NOPE")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "plan_not_found"


def test_meal_log_upsert_persistence_and_ordering() -> None:
    patient_id = "P9998"
    persistence.delete_logs_for_patient(patient_id)

    a = store.put_log(patient_id, _today(-1), "dinner", "SG0001")
    b = store.put_log(patient_id, _today(0), "breakfast", "SG0002")
    c = store.put_log(patient_id, _today(0), "lunch", "SG0003")
    for entry in (a, b, c):
        assert set(entry) == {"patient_id", "date", "meal", "dish_id", "logged_at"}

    # upsert: the newest log for the same slot replaces the previous dish
    replaced = store.put_log(patient_id, _today(0), "lunch", "SG0004")
    assert store.get_log(patient_id, _today(0), "lunch") == replaced
    saved = store.get_log(patient_id, _today(0), "lunch")
    assert saved is not None
    assert saved["dish_id"] == "SG0004"
    assert store.get_log(patient_id, _today(0), "breakfast") == b
    assert store.get_log(patient_id, _today(0), "snack") is None

    # chronological: date ASC, then breakfast/lunch/dinner
    logs = store.list_logs(patient_id)
    assert [(entry["date"], entry["meal"]) for entry in logs] == [
        (_today(-1), "dinner"),
        (_today(0), "breakfast"),
        (_today(0), "lunch"),
    ]

    # inclusive date bounds
    window = store.list_logs(patient_id, date_from=_today(0), date_to=_today(0))
    assert [(entry["date"], entry["meal"]) for entry in window] == [
        (_today(0), "breakfast"),
        (_today(0), "lunch"),
    ]
    assert store.list_logs(patient_id, date_from=_today(5)) == []

    assert store.count_logs(patient_id) == 3
    assert store.count_logs() >= 3

    # persistence across a fresh handle
    with persistence._connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM meal_logs WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
    assert n == 3

    assert store.delete_logs_for_patient(patient_id) == 3
    assert store.count_logs(patient_id) == 0
    assert store.get_log(patient_id, _today(0), "lunch") is None


def test_journal_via_api_effective_envelope(client) -> None:
    patient_id = "P0002"
    body = _run_rules(client, patient_id)
    envelope = body["envelope"]
    proposed_id = envelope["envelope_id"]

    # the fresh proposal was journalled
    approved = client.post(
        f"/envelopes/{proposed_id}/approve",
        json={"clinician_id": "dr-tan", "note": "journal test"},
    )
    assert approved.status_code == 200, approved.text
    approved_id = approved.json()["envelope_id"]

    rows = [
        row
        for row in persistence.list_envelope_history(patient_id)
        if row["envelope_id"] in (proposed_id, approved_id)
    ]
    assert [row["status"] for row in rows] == ["PROPOSED", "APPROVED"]  # ordered
    assert rows[0]["version"] == rows[1]["version"]
    assert rows[1]["snapshot"]["patient_id"] == patient_id

    # the envelope effective TODAY is the (latest) APPROVED one, reconstructed
    effective = persistence.envelope_effective_at(patient_id, _today())
    assert effective is not None
    assert effective.status is EnvelopeStatus.APPROVED
    assert effective.patient_id == patient_id
    assert effective.targets, "reconstructed envelope must carry its targets"
    assert effective.envelope_id == approved_id

    # a date before the first proposal for this patient -> nothing in force
    assert persistence.envelope_effective_at(patient_id, "2000-01-01") is None


def test_journal_ordering_and_tie_break() -> None:
    patient_id = "JTEST-PERSIST"
    first = _hand_envelope(patient_id, "ENV-JTEST-001")
    second = _hand_envelope(
        patient_id, "ENV-JTEST-002", status=EnvelopeStatus.APPROVED
    )
    persistence.journal_envelope(
        first, event="proposed", effective_at="2026-01-10"
    )
    persistence.journal_envelope(
        second, event="approved", effective_at="2026-06-01"
    )

    # before any proposal -> None
    assert persistence.envelope_effective_at(patient_id, "2026-01-09") is None
    # Proposals never establish historical approved coverage.
    assert persistence.envelope_effective_at(patient_id, "2026-01-10") is None
    assert persistence.envelope_effective_at(
        patient_id, "2026-03-01"
    ) is None
    # from the second effective date onwards -> the approved envelope
    assert persistence.envelope_effective_at(patient_id, "2026-06-01") == second
    assert persistence.envelope_effective_at(patient_id, _today()) == second

    # same effective date -> newest journal row wins
    third = _hand_envelope(
        patient_id, "ENV-JTEST-003", status=EnvelopeStatus.APPROVED, sodium_max=1500.0
    )
    persistence.journal_envelope(
        third, event="approved", effective_at="2026-06-01"
    )
    assert persistence.envelope_effective_at(patient_id, _today()) == third

    history = persistence.list_envelope_history(patient_id)
    assert [row["envelope_id"] for row in history] == [
        "ENV-JTEST-001",
        "ENV-JTEST-002",
        "ENV-JTEST-003",
    ]
    assert history[2]["snapshot"]["targets"][0]["value"] == 1500.0


def test_observation_store_roundtrip_chronological() -> None:
    patient_id = "P9997"
    first = persistence.add_observation(
        patient_id, "serum_K_meq_L", 5.4, unit="meq/L", source="lab-a",
        observed_at=_today(-3),
    )
    second = persistence.add_observation(
        patient_id, "serum_PO4_mg_dL", 1.9, unit="mg/dL",
        observed_at=_today(-1),
    )
    third = persistence.add_observation(
        patient_id, "egfr", 52.0, unit="mL/min", observed_at=_today(-2),
    )
    assert first["observation_id"].startswith("OBS-P9997-")
    assert second["observation_id"] != first["observation_id"]
    assert first["recorded_at"]

    rows = persistence.list_observations(patient_id)
    assert [row["observation_id"] for row in rows] == [
        first["observation_id"],
        third["observation_id"],
        second["observation_id"],
    ]  # chronological by observed_at, not insertion order
    assert rows[0]["metric"] == "serum_K_meq_L"
    assert rows[0]["value"] == pytest.approx(5.4)


def test_observations_api(client) -> None:
    patient_id = "P0003"
    resp = client.post(
        "/observations",
        json={
            "patient_id": patient_id,
            "metric": "hba1c_pct",
            "value": 7.8,
            "unit": "%",
            "source": "clinic lab",
        },
    )
    assert resp.status_code == 201, resp.text
    stored = resp.json()
    assert stored["patient_id"] == patient_id
    assert stored["metric"] == "hba1c_pct"
    assert stored["observed_at"] == _today()
    assert stored["recorded_at"]

    listed = client.get("/observations", params={"patient_id": patient_id})
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["count"] >= 1
    assert stored["observation_id"] in [
        row["observation_id"] for row in payload["observations"]
    ]

    # unknown patient -> documented 404 body
    missing = client.post(
        "/observations",
        json={"patient_id": "P_NOPE", "metric": "egfr", "value": 50.0, "unit": "x"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "patient_not_found"
    assert (
        client.get("/observations", params={"patient_id": "P_NOPE"}).status_code
        == 404
    )

    # metric whitelist + extra="forbid" -> 422
    bad_metric = client.post(
        "/observations",
        json={
            "patient_id": patient_id,
            "metric": "cholesterol",
            "value": 5.0,
            "unit": "mmol/L",
        },
    )
    assert bad_metric.status_code == 422
    extra_field = client.post(
        "/observations",
        json={
            "patient_id": patient_id,
            "metric": "egfr",
            "value": 50.0,
            "unit": "x",
            "nonsense": True,
        },
    )
    assert extra_field.status_code == 422

    # invalid observed_at -> 422 invalid_observed_date
    bad_date = client.post(
        "/observations",
        json={
            "patient_id": patient_id,
            "metric": "egfr",
            "value": 50.0,
            "unit": "mL/min",
            "observed_at": "not-a-date",
        },
    )
    assert bad_date.status_code == 422
    assert bad_date.json()["detail"]["error"] == "invalid_observed_date"


def test_simulation_roundtrip() -> None:
    patient_id = "P9996"
    sim_id = persistence.save_simulation(
        patient_id,
        base_envelope_id="ENV-P9996-001",
        proposed_targets=[
            {"nutrient": "sodium_mg", "kind": "max", "value": 1800.0, "unit": "mg"}
        ],
        comparison={"delta": {"sodium_mg": -200.0}, "feasible": True},
    )
    assert sim_id.startswith("SIM-P9996-")
    rows = persistence.list_simulations(patient_id)
    assert rows and rows[-1]["simulation_id"] == sim_id
    row = rows[-1]
    assert row["base_envelope_id"] == "ENV-P9996-001"
    assert row["status"] == "OPEN"
    assert row["proposed_targets"][0]["value"] == 1800.0
    assert row["comparison"]["delta"]["sodium_mg"] == pytest.approx(-200.0)
    assert row["created_at"]


def test_review_item_roundtrip() -> None:
    patient_id = "P9995"
    review_id = persistence.create_review_item(
        patient_id,
        source="adherence-deviation",
        payload={"metric": "sodium_mg", "flag": "worsening", "slope": 0.5},
    )
    assert review_id.startswith("REV-P9995-")

    item = persistence.get_review_item(review_id)
    assert item is not None
    assert item["status"] == "OPEN"
    assert item["acknowledged_at"] is None
    assert item["action"] is None
    assert item["payload"]["flag"] == "worsening"

    open_items = persistence.list_review_items(status="OPEN", patient_id=patient_id)
    assert review_id in [row["review_id"] for row in open_items]

    acked = persistence.acknowledge_review_item(review_id)
    assert acked is not None and acked["status"] == "ACKNOWLEDGED"
    assert acked["acknowledged_at"]
    saved = persistence.get_review_item(review_id)
    assert saved is not None
    assert saved["status"] == "ACKNOWLEDGED"
    assert persistence.list_review_items(status="OPEN", patient_id=patient_id) == []

    actioned = persistence.record_review_action(
        review_id,
        action="revised_envelope_proposed",
        note="tightened sodium to 1800 mg",
        linked_envelope_id="ENV-P9995-002",
    )
    assert actioned is not None
    assert actioned["status"] == "ACTION_RECORDED"
    assert actioned["action"]["action"] == "revised_envelope_proposed"
    assert actioned["action"]["note"] == "tightened sodium to 1800 mg"
    assert actioned["linked_envelope_id"] == "ENV-P9995-002"
    assert persistence.get_review_item(review_id) == actioned

    # unknown ids -> None
    assert persistence.get_review_item("REV-NOPE-999") is None
    assert persistence.acknowledge_review_item("REV-NOPE-999") is None
    assert persistence.record_review_action("REV-NOPE-999", action="x") is None


def test_adherence_store_delegates_to_persistence() -> None:
    patient_id = "P9994"
    persistence.delete_logs_for_patient(patient_id)
    store.put_log(patient_id, _today(), "lunch", "SG0007")
    # the adherence facade and the persistence layer see the same row
    assert store.get_log(patient_id, _today(), "lunch") == persistence.get_log(
        patient_id, _today(), "lunch"
    )
    store.clear()  # wipes every patient's logs, like the old dict store
    assert store.count_logs() == 0
    assert persistence.count_logs() == 0
