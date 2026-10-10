"""Core/API regression tests for the 2026-10-10 maintainability audit.

Focused coverage for the remediated core/API contracts:

* patient create is create-only (409 on existing fixture or durable ids);
* reserved UI lab aliases mirror the canonical current values after
  observations overlay them;
* acknowledgement cannot regress a concurrently recorded action;
* review proposal retries recover the partial success instead of minting a
  duplicate envelope;
* validation-error responses stay strict JSON (nonfinite raw inputs);
* patient profiles reject nonfinite clinical numerics at the boundary;
* envelope rejection retains reviewer attribution in the durable snapshot;
* eGFR ``mL/min`` shorthand stores the already-indexed unit;
* legacy meal-log schema migration is reserved and idempotent.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from backend.app.adherence import store
from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE
from backend.app.models.patient import Patient


@pytest.fixture(autouse=True)
def _isolated_stores():
    """Fresh logs/journal/review rows + snapshot envelope store per test."""
    snapshot = dict(ENVELOPE_STORE)
    store.clear()
    persistence.clear_all()
    yield
    store.clear()
    persistence.clear_all()
    ENVELOPE_STORE.clear()
    ENVELOPE_STORE.update(snapshot)


@pytest.fixture()
def lenient_client():
    """TestClient that returns 500 responses instead of raising them.

    Only the fault-injection test needs the unhandled-error response body;
    every other test keeps the shared strict client.
    """
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Finding 4: patient create is create-only
# ---------------------------------------------------------------------------

_NEW_PATIENT = {
    "patient_id": "p-fix4",
    "name": "Regression Patient",
    "age": 55,
    "sex": "F",
    "weight_kg": 70.0,
    "diagnoses": ["T2D"],
    "egfr": 45.0,
}


def test_create_patient_conflicts_with_fixture_id(client) -> None:
    resp = client.post("/patients", json={**_NEW_PATIENT, "patient_id": "P0001"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "patient_exists"
    assert resp.json()["detail"]["patient_id"] == "P0001"
    # The fixture record is untouched, not shadowed.
    fixture = client.get("/patients/P0001")
    assert fixture.status_code == 200, fixture.text
    assert fixture.json()["patient_id"] == "P0001"


def test_create_patient_repeat_returns_conflict_without_replacing(client) -> None:
    created = client.post("/patients", json=_NEW_PATIENT)
    assert created.status_code == 201, created.text

    repeat = client.post("/patients", json={**_NEW_PATIENT, "weight_kg": 99.0})
    assert repeat.status_code == 409, repeat.text
    assert repeat.json()["detail"]["error"] == "patient_exists"

    fetched = client.get("/patients/p-fix4")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["weight_kg"] == 70.0  # stored profile not replaced


# ---------------------------------------------------------------------------
# Finding 3: reserved UI lab aliases follow the canonical current values
# ---------------------------------------------------------------------------


def test_ui_lab_alias_mirrors_overlaid_canonical_value(client) -> None:
    # A stored lowercase alias (extra key) must not mask later observations.
    payload = {
        **_NEW_PATIENT,
        "patient_id": "p-alias",
        "serum_K_meq_L": 4.0,
        "serum_k": 4.0,  # stale alias stored alongside the canonical key
        "archetype": "renal",
    }
    created = client.post("/patients", json=payload)
    assert created.status_code == 201, created.text

    obs = client.post(
        "/observations",
        json={
            "patient_id": "p-alias",
            "metric": "serum_K_meq_L",
            "value": 6.5,
            "unit": "meq/l",
        },
    )
    assert obs.status_code == 201, obs.text

    resp = client.get("/patients/p-alias")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["serum_K_meq_L"] == 6.5
    assert body["serum_k"] == 6.5  # alias derived from the canonical value
    assert body["archetype"] == "renal"  # unrelated extras preserved
    assert body["id"] == "p-alias"


# ---------------------------------------------------------------------------
# Finding 6: acknowledgement cannot regress a recorded action
# ---------------------------------------------------------------------------


def _seed_review_item(review_id: str, patient_id: str = "P0002") -> str:
    persistence.create_review_item(
        patient_id,
        "hard_violation_day",
        {"key": f"day@2026-10-10", "kind": "ceiling", "severity": "alert",
         "reason": "test", "payload": {}},
        review_id=review_id,
    )
    return review_id


def test_acknowledge_cannot_regress_recorded_action(client) -> None:
    review_id = _seed_review_item("rev-ack-0001")

    acted = persistence.record_review_action(review_id, "contacted_dietitian")
    assert acted["status"] == "ACTION_RECORDED"

    # The racy write path: unconditional acknowledgement would regress this.
    after_ack = persistence.acknowledge_review_item(review_id)
    assert after_ack is not None
    assert after_ack["status"] == "ACTION_RECORDED"
    assert after_ack["action"]["action"] == "contacted_dietitian"

    resp = client.post(f"/review/{review_id}/acknowledge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACTION_RECORDED"


def test_acknowledge_still_advances_open_items(client) -> None:
    review_id = _seed_review_item("rev-ack-0002")

    resp = client.post(f"/review/{review_id}/acknowledge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACKNOWLEDGED"
    assert resp.json()["acknowledged_at"]

    repeat = client.post(f"/review/{review_id}/acknowledge")
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["status"] == "ACKNOWLEDGED"

    missing = client.post("/review/rev-ack-none/acknowledge")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "review_item_not_found"


# ---------------------------------------------------------------------------
# Finding 5: proposal retry recovers the partial success
# ---------------------------------------------------------------------------


def _proposed_envelope_ids(patient_id: str) -> list[str]:
    return [
        row["envelope_id"]
        for row in persistence.list_envelope_history(patient_id)
        if row["status"] == "PROPOSED"
    ]


def test_review_proposal_retry_relinks_orphan_without_duplicate(lenient_client, monkeypatch) -> None:
    review_id = _seed_review_item("rev-prop-0001")
    client = lenient_client

    original = persistence.finalize_review_proposal
    failures = {"count": 0}

    def flaky_finalize_review_proposal(*args, **kwargs):
        if failures["count"] == 0:
            failures["count"] += 1
            raise RuntimeError("injected linkage failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(persistence, "finalize_review_proposal", flaky_finalize_review_proposal)

    first = client.post(f"/review/{review_id}/proposal")
    assert first.status_code == 500, first.text

    # Partial success: the proposal exists, but the review item is unlinked
    # and carries the recoverable pending marker.
    orphan_ids = _proposed_envelope_ids("P0002")
    assert len(orphan_ids) == 1
    row = persistence.get_review_item(review_id)
    assert row["linked_envelope_id"] is None
    assert row["action"]["action"] == "proposal_pending"
    assert row["status"] == "OPEN"  # pending marker did not touch lifecycle

    retry = client.post(f"/review/{review_id}/proposal")
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["envelope_id"] == orphan_ids[0]
    assert body["review_item"]["linked_envelope_id"] == orphan_ids[0]
    assert body["review_item"]["action"]["action"] == "proposal_created"

    # The retry recovered the orphan instead of minting a second proposal.
    assert _proposed_envelope_ids("P0002") == orphan_ids


# ---------------------------------------------------------------------------
# Findings 8 + 9: JSON-safe validation errors; finite clinical numerics
# ---------------------------------------------------------------------------


def test_validation_error_response_is_json_safe(client) -> None:
    # JSON parsers accept the Infinity/NaN literals; the 422 body must not
    # carry them through into non-strict JSON (which would render as a 500).
    resp = client.post(
        "/patients",
        content=(
            '{"patient_id": "p-nonfinite", "age": 61, "sex": "F", '
            '"weight_kg": Infinity, "diagnoses": [], "egfr": NaN}'
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()  # must parse as strict JSON
    assert body["error"] == "validation_error"
    for error in body["detail"]:
        value = error.get("input")
        assert not isinstance(value, float)  # nonfinite floats stringified
    inputs = {error.get("input") for error in body["detail"]}
    assert "inf" in inputs and "nan" in inputs


def test_patient_model_rejects_nonfinite_clinical_numerics() -> None:
    base = {
        "patient_id": "p-nonfinite-model",
        "age": 61,
        "sex": "F",
        "weight_kg": 70.0,
    }
    with pytest.raises(ValidationError):
        Patient(**{**base, "weight_kg": float("inf")})
    with pytest.raises(ValidationError):
        Patient(**{**base, "egfr": float("nan")})
    with pytest.raises(ValidationError):
        Patient(**{**base, "serum_K_meq_L": float("inf")})
    # Finite values (and bounds-legal None) are unaffected.
    assert Patient(**base).egfr is None


# ---------------------------------------------------------------------------
# Finding 11: rejection retains reviewer attribution
# ---------------------------------------------------------------------------


def test_reject_retains_reviewer_attribution(client) -> None:
    run = client.post("/rules/run", json={"patient_id": "P0003"})
    assert run.status_code == 200, run.text
    envelope_id = run.json()["envelope"]["envelope_id"]

    resp = client.post(
        f"/envelopes/{envelope_id}/reject",
        json={"rejected_by": "dr-lim", "reason": "stale labs"},
    )
    assert resp.status_code == 200, resp.text
    rejected = resp.json()
    assert rejected["status"] == "REJECTED"
    assert rejected["approved_by"] is None
    trace = [r for r in rejected["fired_rules"] if r["rule_id"] == "CLINICIAN-REJECT"]
    assert trace and trace[-1]["patient_summary"] == "rejected by dr-lim"
    assert "stale labs" in trace[-1]["action_summary"]

    # Attribution is durable: it survives a fresh read of the snapshot.
    fetched = client.get(f"/envelopes/{envelope_id}")
    assert fetched.status_code == 200, fetched.text
    persisted = [r for r in fetched.json()["fired_rules"]
                 if r["rule_id"] == "CLINICIAN-REJECT"]
    assert persisted and persisted[-1]["patient_summary"] == "rejected by dr-lim"


# ---------------------------------------------------------------------------
# Finding 12: eGFR mL/min shorthand is the already-indexed unit
# ---------------------------------------------------------------------------


def test_observation_egfr_ml_min_shorthand_stores_indexed_unit(client) -> None:
    resp = client.post(
        "/observations",
        json={
            "patient_id": "P0001",
            "metric": "egfr",
            "value": 42,
            "unit": "mL/min",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["unit"] == "mL/min/1.73m2"


# ---------------------------------------------------------------------------
# Finding 7 (contract lock): malformed inline rule inputs return 422
# ---------------------------------------------------------------------------


def test_rules_run_malformed_inline_input_returns_422(client) -> None:
    inline = {
        "patient_id": "p-malformed",
        "sex": "F",
        "diagnoses": ["T2D"],
    }
    bad_age = client.post(
        "/rules/run", json={**inline, "age": "not-a-number", "weight_kg": 70.0}
    )
    assert bad_age.status_code == 422, bad_age.text
    assert bad_age.json()["detail"]["error"] == "validation_error"

    bad_weight = client.post(
        "/rules/run", json={**inline, "age": 61, "weight_kg": "heavy"}
    )
    assert bad_weight.status_code == 422, bad_weight.text

    missing_weight = client.post("/rules/run", json={**inline, "age": 61})
    assert missing_weight.status_code == 422, missing_weight.text


# ---------------------------------------------------------------------------
# Finding 10: legacy schema migration is reserved and idempotent
# ---------------------------------------------------------------------------


def test_legacy_meal_logs_schema_migration_is_idempotent(tmp_path, monkeypatch) -> None:
    db = tmp_path / "legacy-app.sqlite3"
    monkeypatch.setenv("CARELOOP_APP_DB", str(db))

    # Old-schema database: meal_logs without the items_json column.
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE meal_logs ("
        "patient_id TEXT NOT NULL, date TEXT NOT NULL, meal TEXT NOT NULL, "
        "dish_id TEXT NOT NULL, logged_at TEXT NOT NULL, "
        "PRIMARY KEY (patient_id, date, meal))"
    )
    conn.commit()
    conn.close()

    persistence.init_db()
    conn = sqlite3.connect(db)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(meal_logs)")}
    conn.close()
    assert "items_json" in columns

    # A later initializer (fresh process view of the same path) rechecks the
    # column under the write reservation instead of ALTERing a second time.
    persistence._INITIALIZED.discard(str(db))
    persistence.init_db()  # must not raise "duplicate column name"
