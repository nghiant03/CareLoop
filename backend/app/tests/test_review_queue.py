"""Review-queue workflows and historical envelope-version attribution.

Covers review workflows end to end:

* **Envelope-version attribution**: history is scored against the envelope
  effective on each consumption date. After approve → log day A → edit +
  re-approve → log day B, day A is scored against the pre-edit limits and
  day B against the post-edit limits. Assertions check each day's
  ``envelope_id``/``version`` and differing sodium limits. A single-envelope
  window retains plain series keys and legacy fields, with only additive
  new fields.
* **Closed loop**: a worsening sodium trend flag surfaces in
  ``GET /review/queue``. After acknowledgement, recording an action removes the
  item from the open queue. ``POST /review/{id}/proposal`` then mints a linked
  PROPOSED envelope. A subsequent observation appears in ``GET /observations``.

Also covers logging completeness, deterministic review ids (idempotent
derivation), hard-violation-day items and lab-trend items.

The envelope journal is the attribution source of truth; tests backdate
approval rows explicitly via ``persistence.journal_envelope`` so historical
dates resolve to the pre-edit version.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.app.adherence import store
from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE, get_envelope, put_envelope
from backend.app.models.envelope import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)
from backend.mining.trends import detect_trends

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def _mount_review_router():
    """Attach the review router only if the imported app lacks its queue route.

    Normal application imports already include it; standalone test app setups
    may omit the route.
    """
    from backend.app.api import review as review_module
    from backend.app.main import app

    if not any(getattr(route, "path", "") == "/review/queue" for route in app.routes):
        app.include_router(review_module.router)
    yield


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


def _today(offset_days: int = 0) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset_days)).isoformat()


def _log(client, patient_id: str, day: str, meal: str, dish_id: str):
    return client.post(
        "/adherence/log",
        json={"patient_id": patient_id, "date": day, "meal": meal, "dish_id": dish_id},
    )


def _hand_built_envelope(patient_id: str, sodium_max: float) -> NutrientEnvelope:
    envelope = NutrientEnvelope(
        envelope_id=f"env-review-{patient_id}",
        patient_id=patient_id,
        status=EnvelopeStatus.APPROVED,
        patient_snapshot=PatientSummary(
            patient_id=patient_id, age=60, sex="M", weight_kg=70.0
        ),
        targets=[
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=sodium_max, unit="mg"),
        ],
        priority_basis="test fixture: review-queue regression",
    )
    put_envelope(envelope)
    persistence.journal_envelope(envelope, effective_at=_today(-90))
    return envelope


# ---------------------------------------------------------------------------
# Envelope-version attribution
# ---------------------------------------------------------------------------


def test_history_scores_each_day_against_its_envelope_version(client) -> None:
    """approve -> log day A -> edit + re-approve -> log day B: day A must be
    scored against the pre-edit sodium ceiling, day B against the post-edit
    one, with per-day envelope id/version attribution."""
    run = client.post("/rules/run", json={"patient_id": "P0001"})
    assert run.status_code == 200, run.text
    envelope = run.json()["envelope"]
    envelope_id = envelope["envelope_id"]
    original_sodium_max = next(
        t["value"] for t in envelope["targets"] if t["nutrient"] == "sodium_mg" and t["kind"] == "max"
    )

    approve = client.post(f"/envelopes/{envelope_id}/approve", json={})
    assert approve.status_code == 200, approve.text

    day_a = _today(offset_days=-3)
    day_b = _today()
    # Backdate the v1 approval so the journal covers day A (the rules run and
    # the approval both journal at "today" by default).
    envelope = get_envelope(envelope_id)
    assert envelope is not None
    persistence.journal_envelope(envelope, event="APPROVED", effective_at=day_a)

    assert _log(client, "P0001", day_a, "lunch", "SG0001").status_code == 201

    # Clinician tightens the sodium ceiling and re-approves (version 2).
    edit = client.post(
        f"/envelopes/{envelope_id}/edit",
        json={
            "targets": [
                {"nutrient": "sodium_mg", "kind": "max", "value": 1.0, "unit": "mg"},
                {"nutrient": "protein_g", "kind": "min", "value": 25.0, "unit": "g"},
            ]
        },
    )
    assert edit.status_code == 200, edit.text
    approve2 = client.post(f"/envelopes/{envelope_id}/approve", json={})
    assert approve2.status_code == 200, approve2.text

    assert _log(client, "P0001", day_b, "lunch", "SG0001").status_code == 201

    resp = client.get("/adherence/P0001/summary", params={"days": 14})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days_logged"] == 2

    by_date = {day["date"]: day for day in body["days"]}
    assert set(by_date) == {day_a, day_b}
    day_a_row, day_b_row = by_date[day_a], by_date[day_b]

    # Same envelope id, two versions; each day attributed to its own version.
    assert day_a_row["envelope_id"] == envelope_id
    assert day_b_row["envelope_id"] == envelope_id
    assert {day_a_row["envelope_version"], day_b_row["envelope_version"]} == {1, 2}
    assert day_a_row["envelope_version"] == 1
    assert day_b_row["envelope_version"] == 2

    # The limits actually applied differ per day.
    sodium_a = next(r for r in day_a_row["nutrients"] if r["nutrient"] == "sodium_mg")
    sodium_b = next(r for r in day_b_row["nutrients"] if r["nutrient"] == "sodium_mg")
    assert sodium_a["limit"] == pytest.approx(original_sodium_max)
    assert sodium_b["limit"] == pytest.approx(1.0)
    assert sodium_a["limit"] != sodium_b["limit"]

    # Attribution metadata on the response.
    versions = body["envelope_versions_used"]
    assert len(versions) == 2
    assert {v["version"] for v in versions} == {1, 2}
    assert all(v["envelope_id"] == envelope_id for v in versions)
    assert all(v["status"] == "APPROVED" for v in versions)
    days_by_version = {v["version"]: v["days"] for v in versions}
    assert days_by_version[1] == [day_a]
    assert days_by_version[2] == [day_b]
    assert body["unattributed_days"] == []

    # Deviation endpoint: multi-version window -> prefixed, disambiguated keys.
    dev = client.get("/adherence/P0001/deviation", params={"days": 14})
    assert dev.status_code == 200, dev.text
    series = dev.json()["series"]
    assert f"{envelope_id}::v1::sodium_mg" in series
    assert f"{envelope_id}::v2::sodium_mg" in series
    assert series[f"{envelope_id}::v1::sodium_mg"]["limit"] == pytest.approx(original_sodium_max)
    assert series[f"{envelope_id}::v2::sodium_mg"]["limit"] == pytest.approx(1.0)
    assert [p["date"] for p in series[f"{envelope_id}::v1::sodium_mg"]["points"]] == [day_a]
    assert [p["date"] for p in series[f"{envelope_id}::v2::sodium_mg"]["points"]] == [day_b]


def test_single_envelope_response_keeps_legacy_shape(client) -> None:
    """With only one effective envelope the responses keep the exact legacy
    key set (plus the additive attribution fields) and plain series keys."""
    envelope = _hand_built_envelope("P0002", sodium_max=100_000.0)
    assert _log(client, "P0002", _today(), "lunch", "SG0001").status_code == 201

    resp = client.get("/adherence/P0002/summary", params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "patient_id", "envelope_id", "envelope_status", "informational_only",
        "notice", "window", "days_logged", "days", "aggregate",
        "envelope_versions_used", "unattributed_days",
    }
    assert body["envelope_id"] == envelope.envelope_id
    assert body["days"][0]["envelope_id"] == envelope.envelope_id
    assert body["days"][0]["envelope_version"] == 1
    assert body["envelope_versions_used"] == [
        {
            "envelope_id": envelope.envelope_id,
            "version": 1,
            "status": "APPROVED",
            "days": [_today()],
        }
    ]
    assert body["unattributed_days"] == []
    assert body["aggregate"]["complete_days"] == 0
    assert body["aggregate"]["fraction_complete"] == 0.0

    dev = client.get("/adherence/P0002/deviation", params={"days": 7})
    assert dev.status_code == 200, dev.text
    dev_body = dev.json()
    assert set(dev_body) == {
        "patient_id", "envelope_id", "envelope_status", "informational_only",
        "notice", "window", "series", "flags",
        "envelope_versions_used", "unattributed_days",
    }
    # single-envelope case: plain series keys, no "<envelope_id>::" prefix
    assert all("::" not in key for key in dev_body["series"])
    assert set(dev_body["series"]) == {"sodium_mg"}
    for flag in dev_body["flags"]:
        assert flag["envelope_id"] == envelope.envelope_id


# ---------------------------------------------------------------------------
# Review queue: derivation, deterministic ids, lifecycle
# ---------------------------------------------------------------------------


def _queue(client, **params):
    resp = client.get("/review/queue", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_queue_hard_violation_day_item_is_deterministic(client) -> None:
    """A non-compliant day derives a ``hard_violation_day`` item; repeating
    the derivation maps to the same review id (no duplicates)."""
    _hand_built_envelope("P0007", sodium_max=1.0)  # any dish violates
    assert _log(client, "P0007", _today(), "lunch", "SG0001").status_code == 201

    first = _queue(client, patient_id="P0007")
    day_items = [i for i in first["items"] if i["source"] == "hard_violation_day"]
    assert len(day_items) == 1
    item = day_items[0]
    assert item["key"] == f"day@{_today()}"
    assert item["kind"] == "ceiling"
    assert item["severity"] == "alert"
    assert item["status"] == "OPEN"
    assert item["patient_id"] == "P0007"
    assert item["reason"]
    assert item["payload"]["date"] == _today()
    assert item["payload"]["compliant"] is False
    # contributors ride along in the day payload
    assert any(
        row.get("contributors") for row in item["payload"]["nutrients"]
    )

    second = _queue(client, patient_id="P0007")
    assert second["items"] == first["items"]  # deterministic ids, no dupes
    assert persistence.get_review_item(item["review_id"]) is not None


def test_queue_lab_trend_item_for_fixture_patient(client) -> None:
    """Patients from data/patients.json with a rising lab series get a
    ``lab_trend`` item keyed ``lab@<patient_id>:<analyte>``."""
    raw = json.loads((_REPO_ROOT / "data" / "patients.json").read_text())
    patients = raw["patients"] if isinstance(raw, dict) else raw
    flags = detect_trends(patients)
    assert flags, "dataset expected to contain at least one rising lab trend"
    flag = flags[0]
    patient_id, analyte = flag["patient_id"], flag["analyte"]

    body = _queue(client, patient_id=patient_id)
    lab_items = [i for i in body["items"] if i["source"] == "lab_trend"]
    assert lab_items, "expected at least one lab_trend item"
    item = next(i for i in lab_items if i["key"] == f"lab@{patient_id}:{analyte}")
    assert item["kind"] == analyte
    assert item["severity"] == ("alert" if flag["severity"] == "urgent" else "review")
    assert item["payload"]["analyte"] == analyte
    assert item["reason"] == flag["reason"]


def test_closed_loop_flag_acknowledge_action_proposal_observation(client) -> None:
    """Closed clinical loop: worsening sodium trend -> queue item ->
    acknowledge -> recorded action -> linked PROPOSED envelope proposal ->
    subsequent clinical observation."""
    envelope = _hand_built_envelope("P0009", sodium_max=100.0)

    # Three consecutive days of increasingly salty lunches -> worsening flag.
    from backend.optim.real_data import load_dishes

    by_sodium = sorted(load_dishes(), key=lambda d: d.nutrient("sodium_mg"))
    picks = [by_sodium[0], by_sodium[len(by_sodium) // 2], by_sodium[-1]]
    for i, dish in enumerate(picks):
        day = _today(offset_days=i - 2)  # today-2, today-1, today
        assert _log(client, "P0009", day, "lunch", dish.dish_id).status_code == 201
        for meal in ("breakfast", "dinner"):
            assert _log(client, "P0009", day, meal, by_sodium[0].dish_id).status_code == 201

    body = _queue(client, patient_id="P0009")
    flag_items = [i for i in body["items"] if i["source"] == "adherence_flag"]
    assert len(flag_items) >= 1
    item = flag_items[0]
    assert item["status"] == "OPEN"
    assert item["kind"] == "sodium_mg worsening"
    assert item["severity"] in ("alert", "review")
    assert item["key"] == f"{envelope.envelope_id}::sodium_mg@{_today()}"
    assert item["payload"]["direction"] == "worsening"
    assert item["payload"]["contributors"], "flag payload carries contributors"
    review_id = item["review_id"]

    # Acknowledge (idempotent).
    ack = client.post(f"/review/{review_id}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "ACKNOWLEDGED"
    assert ack.json()["acknowledged_at"]
    ack_again = client.post(f"/review/{review_id}/acknowledge")
    assert ack_again.status_code == 200, ack_again.text
    assert ack_again.json()["status"] == "ACKNOWLEDGED"

    # The open queue no longer lists it; the audit endpoint does.
    open_body = _queue(client, patient_id="P0009", status="open")
    assert review_id not in [i["review_id"] for i in open_body["items"]]
    acked_view = client.get(
        "/review/items", params={"patient_id": "P0009", "status": "acknowledged"}
    )
    assert acked_view.status_code == 200, acked_view.text
    assert review_id in [i["review_id"] for i in acked_view.json()["items"]]

    # Record the clinician's action -> item becomes actioned.
    action = client.post(
        f"/review/{review_id}/action", json={"action": "contacted_dietitian"}
    )
    assert action.status_code == 200, action.text
    acted = action.json()
    assert acted["status"] == "ACTION_RECORDED"
    assert acted["action"]["action"] == "contacted_dietitian"
    assert acted["action"]["recorded_at"]
    # body validation: extra fields forbidden
    bad = client.post(
        f"/review/{review_id}/action",
        json={"action": "x", "unexpected": True},
    )
    assert bad.status_code == 422

    # Sequential re-derivation preserves the recorded action despite a persistent condition.
    open_again = _queue(client, patient_id="P0009", status="open")
    assert review_id not in [i["review_id"] for i in open_again["items"]]
    actioned_view = client.get(
        "/review/items", params={"patient_id": "P0009", "status": "actioned"}
    )
    assert review_id in [i["review_id"] for i in actioned_view.json()["items"]]

    # Proposal: same code path as POST /rules/run -> linked PROPOSED envelope.
    proposal = client.post(f"/review/{review_id}/proposal")
    assert proposal.status_code == 200, proposal.text
    proposal_body = proposal.json()
    envelope_id = proposal_body["envelope_id"]
    assert envelope_id != envelope.envelope_id
    assert proposal_body["review_item"]["linked_envelope_id"] == envelope_id
    assert proposal_body["review_item"]["action"]["action"] == "proposal_created"

    created = client.get(f"/envelopes/{envelope_id}")
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "PROPOSED"

    # Subsequent observation closes the clinical loop.
    obs = client.post(
        "/observations",
        json={
            "patient_id": "P0009",
            "metric": "serum_K_meq_L",
            "value": 5.1,
            "unit": "mmol/L",
            "source": "follow-up after dietitian contact",
        },
    )
    assert obs.status_code == 201, obs.text
    listed = client.get("/observations", params={"patient_id": "P0009"})
    assert listed.status_code == 200, listed.text
    assert any(
        o["observation_id"] == obs.json()["observation_id"]
        for o in listed.json()["observations"]
    )


def test_review_unknown_item_404(client) -> None:
    for path, body in (
        ("/review/NOPE/acknowledge", None),
        ("/review/NOPE/action", {"action": "x"}),
        ("/review/NOPE/proposal", None),
    ):
        resp = client.post(path, json=body)
        assert resp.status_code == 404, (path, resp.status_code)
        assert resp.json()["detail"]["error"] == "review_item_not_found"


def test_review_items_endpoint_lists_persisted_history(client) -> None:
    _hand_built_envelope("P0008", sodium_max=1.0)
    assert _log(client, "P0008", _today(), "dinner", "SG0003").status_code == 201
    body = _queue(client, patient_id="P0008")
    assert body["count"] >= 1

    items = client.get("/review/items", params={"patient_id": "P0008"})
    assert items.status_code == 200, items.text
    listed = items.json()
    assert listed["count"] == body["count"]
    created = [i["created_at"] for i in listed["items"]]
    assert created == sorted(created)  # chronological
    # every persisted item carries the full public shape
    for item in listed["items"]:
        assert set(item) == {
            "review_id", "patient_id", "source", "key", "kind", "severity",
            "reason", "status", "created_at", "acknowledged_at", "payload",
            "action", "linked_envelope_id",
        }
