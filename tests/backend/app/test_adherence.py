from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.adherence import store
from backend.app.core.approval_gate import ENVELOPE_STORE, put_envelope
from backend.optim.real_data import load_dishes
from backend.optim.toy_data import NUTRIENT_KEYS
from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


@pytest.fixture(autouse=True)
def _isolated_clinical_state(pg_databases, monkeypatch):
    monkeypatch.setenv("CARELOOP_APP_DATABASE_URL", pg_databases["clinical"])


def _today(offset_days: int = 0) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset_days)).isoformat()


def _log(client, patient_id: str, day: str, meal: str, dish_id: str):
    return client.post(
        "/adherence/log",
        json={"patient_id": patient_id, "date": day, "meal": meal, "dish_id": dish_id},
    )


def _hand_built_envelope(patient_id: str, sodium_max: float, protein_min: float, energy_target: float) -> NutrientEnvelope:
    envelope = NutrientEnvelope(
        envelope_id=f"env-test-{patient_id}",
        patient_id=patient_id,
        status=EnvelopeStatus.APPROVED,
        patient_snapshot=PatientSummary(
            patient_id=patient_id, age=60, sex="M", weight_kg=70.0
        ),
        targets=[
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=sodium_max, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=protein_min, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=energy_target, unit="kcal"),
        ],
        priority_basis="test fixture: tunable hard/soft limits",
    )
    put_envelope(envelope)
    from backend.app.core import persistence
    persistence.journal_envelope(envelope, effective_at=_today(-90))
    return envelope


def _dish(dish_id: str):
    for dish in load_dishes():
        if dish.dish_id == dish_id:
            return dish
    raise AssertionError(f"dish {dish_id} missing from dataset")


def test_log_meal_returns_entry(client) -> None:
    resp = _log(client, "P0001", _today(), "lunch", "SG0001")
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert entry == {
        "patient_id": "P0001",
        "date": _today(),
        "meal": "lunch",
        "dish_id": "SG0001",
        "logged_at": entry["logged_at"],
    }
    assert entry["logged_at"]


def test_log_unknown_patient_404(client) -> None:
    resp = _log(client, "NOPE", _today(), "lunch", "SG0001")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "patient_not_found"


def test_log_unknown_dish_404(client) -> None:
    resp = _log(client, "P0001", _today(), "lunch", "SG9999")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dish_not_found"
    assert store.count_logs("P0001") == 0


def test_log_invalid_date_422(client) -> None:
    resp = _log(client, "P0001", "not-a-date", "lunch", "SG0001")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "invalid_date"


def test_log_invalid_meal_422(client) -> None:
    resp = client.post(
        "/adherence/log",
        json={"patient_id": "P0001", "date": _today(), "meal": "brunch", "dish_id": "SG0001"},
    )
    assert resp.status_code == 422, resp.text


def test_upsert_replaces_same_slot(client) -> None:
    day = _today()
    assert _log(client, "P0001", day, "lunch", "SG0001").status_code == 201
    assert _log(client, "P0001", day, "lunch", "SG0002").status_code == 201
    assert store.count_logs("P0001") == 1
    stored = store.get_log("P0001", day, "lunch")
    assert stored is not None
    assert stored["dish_id"] == "SG0002"


def test_summary_totals_match_dish_data(client) -> None:
    run = client.post("/rules/run", json={"patient_id": "P0001"})
    assert run.status_code == 200, run.text
    assert client.post(f"/envelopes/{run.json()['envelope']['envelope_id']}/approve", json={}).status_code == 200

    day = _today()
    _log(client, "P0001", day, "breakfast", "SG0001")
    _log(client, "P0001", day, "lunch", "SG0002")
    _log(client, "P0001", day, "dinner", "SG0003")

    resp = client.get("/adherence/P0001/summary", params={"days": 14})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days_logged"] == 1
    day_row = body["days"][0]
    assert day_row["date"] == day
    assert [m["meal"] for m in day_row["meals"]] == ["breakfast", "lunch", "dinner"]

    expected = {k: 0.0 for k in NUTRIENT_KEYS}
    for dish_id in ("SG0001", "SG0002", "SG0003"):
        for key in NUTRIENT_KEYS:
            expected[key] += _dish(dish_id).nutrient(key)
    for key, value in expected.items():
        assert day_row["totals"][key] == pytest.approx(value, abs=1e-6)


def test_hard_vs_soft_classification(client) -> None:
    _hand_built_envelope("P0007", sodium_max=1.0, protein_min=500.0, energy_target=1.0)
    _log(client, "P0007", _today(), "lunch", "SG0001")

    resp = client.get("/adherence/P0007/summary", params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    day_row = body["days"][0]
    rows = {r["nutrient"]: r for r in day_row["nutrients"]}

    sodium = rows["sodium_mg"]
    assert sodium["kind"] == "max"
    assert sodium["status"] == "hard_violation"
    assert sodium["direction"] == "over"
    assert sodium["total"] > sodium["limit"]
    assert day_row["compliant"] is False
    assert body["aggregate"]["hard_violation_days"] == 1
    assert body["aggregate"]["hard_violations_by_nutrient"] == {"sodium_mg": 1}

    protein = rows["protein_g"]
    assert protein["kind"] == "min"
    assert protein["status"] == "soft_gap"
    assert protein["direction"] == "under"

    energy = rows["energy_kcal"]
    assert energy["kind"] == "target"
    assert energy["status"] == "soft_gap"
    assert energy["direction"] == "over"

    assert body["aggregate"]["soft_gaps_by_nutrient"] == {}


def test_compliant_day_all_ok(client) -> None:
    _hand_built_envelope("P0009", sodium_max=100_000.0, protein_min=0.0, energy_target=100_000.0)
    _log(client, "P0009", _today(), "dinner", "SG0001")

    resp = client.get("/adherence/P0009/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    day_row = body["days"][0]
    assert day_row["compliant"] is True
    assert day_row["hard_violations"] == []
    rows = {r["nutrient"]: r for r in day_row["nutrients"]}
    assert rows["sodium_mg"]["status"] == "ok"
    assert rows["protein_g"]["status"] == "ok"
    assert rows["energy_kcal"]["status"] == "soft_gap"
    assert rows["energy_kcal"]["direction"] == "under"


def test_summary_unknown_patient_404(client) -> None:
    resp = client.get("/adherence/NOPE/summary")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "patient_not_found"


def test_summary_no_envelope_404(client) -> None:
    ENVELOPE_STORE.pop("env-test-P0010", None)
    resp = client.get("/adherence/P0010/summary")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "envelope_not_found"


def test_days_param_validated(client) -> None:
    resp = client.get("/adherence/P0001/summary", params={"days": 0})
    assert resp.status_code == 422, resp.text
    resp = client.get("/adherence/P0001/summary", params={"days": 500})
    assert resp.status_code == 422, resp.text


def test_proposed_envelope_is_informational_only(client) -> None:
    run = client.post("/rules/run", json={"patient_id": "P0001"})
    assert run.status_code == 200, run.text
    assert run.json()["envelope"]["status"] == "PROPOSED"

    resp = client.get("/adherence/P0001/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["envelope_status"] == "PROPOSED"
    assert body["informational_only"] is True
    assert "not been approved" in body["notice"]

    dev = client.get("/adherence/P0001/deviation")
    assert dev.status_code == 200, dev.text
    assert dev.json()["informational_only"] is True


def test_deviation_worsening_sodium_flag(client) -> None:
    _hand_built_envelope("P0009", sodium_max=100.0, protein_min=0.0, energy_target=50_000.0)

    by_sodium = sorted(load_dishes(), key=lambda d: d.nutrient("sodium_mg"))
    picks = [by_sodium[i] for i in (0, len(by_sodium) // 4, len(by_sodium) // 2, 3 * len(by_sodium) // 4, len(by_sodium) - 1)]
    assert len({d.dish_id for d in picks}) == 5
    exposures = []
    for i, dish in enumerate(picks):
        day = _today(offset_days=i - 4)
        assert _log(client, "P0009", day, "lunch", dish.dish_id).status_code == 201
        for meal in ("breakfast", "dinner"):
            assert _log(client, "P0009", day, meal, by_sodium[0].dish_id).status_code == 201
        exposures.append(max(0.0, dish.nutrient("sodium_mg") + 2 * by_sodium[0].nutrient("sodium_mg") - 100.0))

    resp = client.get("/adherence/P0009/deviation", params={"days": 14})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    sodium = body["series"]["sodium_mg"]
    assert sodium["kind"] == "max"
    points = sodium["points"]
    assert [p["date"] for p in points] == [_today(offset_days=i - 4) for i in range(5)]
    for point, expected in zip(points, exposures):
        assert point["exposure"] == pytest.approx(expected, abs=1e-3)

    flags = {f["nutrient"]: f for f in body["flags"]}
    sodium_flag = flags["sodium_mg"]
    assert sodium_flag["direction"] == "worsening"
    assert sodium_flag["slope_pct_per_day"] > 1.0
    assert sodium_flag["severity"] in ("alert", "review")
    assert "sodium_mg" in sodium_flag["reason"]


def test_deviation_flat_series_no_flags(client) -> None:
    _hand_built_envelope("P0007", sodium_max=100.0, protein_min=0.0, energy_target=50_000.0)
    for i in range(4):
        for meal in ("breakfast", "lunch", "dinner"):
            assert _log(client, "P0007", _today(offset_days=i - 3), meal, "SG0001").status_code == 201

    resp = client.get("/adherence/P0007/deviation")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for series in body["series"].values():
        assert len(series["points"]) == 4
        assert all(point["complete"] for point in series["points"])
        assert len({point["exposure"] for point in series["points"]}) == 1
    assert body["flags"] == []


def test_deviation_unknown_patient_404(client) -> None:
    resp = client.get("/adherence/NOPE/deviation")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "patient_not_found"


def test_endpoints_deterministic(client) -> None:
    _hand_built_envelope("P0007", sodium_max=100.0, protein_min=0.0, energy_target=50_000.0)
    _log(client, "P0007", _today(), "lunch", "SG0001")
    _log(client, "P0007", _today(offset_days=-1), "dinner", "SG0002")

    first = client.get("/adherence/P0007/summary").json()
    second = client.get("/adherence/P0007/summary").json()
    assert first == second

    first_dev = client.get("/adherence/P0007/deviation").json()
    second_dev = client.get("/adherence/P0007/deviation").json()
    assert first_dev == second_dev
