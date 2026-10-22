from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.adherence import analysis, store
from backend.app.core.approval_gate import ENVELOPE_STORE
from shared.envelope_schema import (
    CitationSource,
    ConstraintKind,
    EnvelopeStatus,
    ExclusionFlag,
    ExclusionKind,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


@pytest.fixture(autouse=True)
def _clean_meal_logs():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def _isolated_envelope_store():
    snapshot = dict(ENVELOPE_STORE)
    yield
    ENVELOPE_STORE.clear()
    ENVELOPE_STORE.update(snapshot)


class StubDish:
    def __init__(self, dish_id: str, nutrients: dict[str, float], **attrs):
        self.dish_id = dish_id
        self.name = attrs.get("name", dish_id)
        self.category = attrs.get("category", "test")
        self.ingredients = attrs.get("ingredients", ())
        self.tags = attrs.get("tags", ())
        self._nutrients = nutrients

    def nutrient(self, key: str) -> float:
        return self._nutrients.get(key, 0.0)


def _envelope(patient_id: str, targets, exclusions=None) -> NutrientEnvelope:
    return NutrientEnvelope(
        envelope_id=f"env-semantics-{patient_id}",
        patient_id=patient_id,
        status=EnvelopeStatus.APPROVED,
        patient_snapshot=PatientSummary(
            patient_id=patient_id, age=60, sex="M", weight_kg=70.0
        ),
        targets=list(targets),
        exclusions=list(exclusions or []),
        priority_basis="test fixture: adherence-semantics regression",
    )


def _logs(patient_id: str, days_and_dishes: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"patient_id": patient_id, "date": day, "meal": "lunch", "dish_id": dish_id}
        for day, dish_id in days_and_dishes
    ]


def _complete_logs(logs, dishes):
    dishes["ZERO"] = StubDish("ZERO", {})
    return logs + [dict(entry, meal=meal, dish_id="ZERO")
                   for entry in logs for meal in ("breakfast", "dinner")]


_CITATION = CitationSource(
    guideline="Test Guideline", section="1.0", rule_id="R-TEST"
)


def test_min_shortfall_exposure_rises_and_flags_worsening() -> None:
    patient = "P0001"
    envelope = _envelope(
        patient,
        [NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=25.0, unit="g")],
    )
    dishes = {
        f"F{i}": StubDish(f"F{i}", {"fiber_g": fiber})
        for i, fiber in enumerate([20.0, 15.0, 10.0])
    }
    days = ["2026-03-01", "2026-03-02", "2026-03-03"]
    logs = _logs(patient, list(zip(days, ["F0", "F1", "F2"])))
    logs = _complete_logs(logs, dishes)

    result = analysis.analyse_patient(logs, envelope, dishes)
    series = result["series"]["fiber_g"]
    assert series["kind"] == "min"
    assert series["limit"] == 25.0
    assert [p["total"] for p in series["points"]] == [20.0, 15.0, 10.0]
    assert [p["exposure"] for p in series["points"]] == pytest.approx([20.0, 40.0, 60.0])
    assert [p["pct"] for p in series["points"]] == pytest.approx([-20.0, -40.0, -60.0])

    flags = result["flags"]
    assert len(flags) == 1
    flag = flags[0]
    assert flag["nutrient"] == "fiber_g"
    assert flag["kind"] == "min"
    assert flag["direction"] == "worsening"
    assert flag["slope_pct_per_day"] == pytest.approx(20.0)
    assert flag["severity"] == "alert"
    assert flag["projected_3d_exposure_pct"] == pytest.approx(120.0)


def test_min_satisfied_day_has_zero_exposure() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=25.0, unit="g")],
    )
    dishes = {"F0": StubDish("F0", {"fiber_g": 30.0})}
    result = analysis.analyse_patient(
        _logs("P0001", [("2026-03-01", "F0")]), envelope, dishes
    )
    assert result["series"]["fiber_g"]["points"][0]["exposure"] == 0.0
    assert result["series"]["fiber_g"]["points"][0]["pct"] == pytest.approx(20.0)


def test_band_nutrient_gets_one_series_per_constraint() -> None:
    patient = "P0001"
    envelope = _envelope(
        patient,
        [
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=50.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MAX, value=60.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg"),
        ],
    )
    days = ["2026-03-01", "2026-03-02"]
    dishes = {
        "P1": StubDish("P1", {"protein_g": 55.0}),
        "P2": StubDish("P2", {"protein_g": 70.0}),
    }
    logs = _logs(patient, [("2026-03-01", "P1"), ("2026-03-02", "P2")])

    result = analysis.analyse_patient(logs, envelope, dishes)
    series = result["series"]

    assert set(series) == {"protein_g:min", "protein_g:max", "sodium_mg"}
    assert series["sodium_mg"]["kind"] == "max"
    assert series["sodium_mg"]["limit"] == 1000.0

    min_series = series["protein_g:min"]
    max_series = series["protein_g:max"]
    assert min_series["kind"] == "min"
    assert min_series["limit"] == 50.0
    assert max_series["kind"] == "max"
    assert max_series["limit"] == 60.0

    for s in (min_series, max_series, series["sodium_mg"]):
        assert [p["date"] for p in s["points"]] == days

    assert min_series["points"][0]["exposure"] == 0.0
    assert max_series["points"][0]["exposure"] == 0.0
    assert max_series["points"][1]["exposure"] == pytest.approx(
        (70.0 - 60.0) / 60.0 * 100.0, abs=1e-3
    )
    assert min_series["points"][1]["exposure"] == 0.0
    under = analysis.deviation_series(
        [{"date": "2026-03-03", "totals": {"protein_g": 40.0}}], envelope
    )
    assert under["protein_g:min"]["points"][0]["exposure"] == pytest.approx(20.0)
    assert under["protein_g:max"]["points"][0]["exposure"] == 0.0


def test_band_nutrient_soft_gap_rows_per_constraint() -> None:
    envelope = _envelope(
        "P0001",
        [
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=50.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MAX, value=60.0, unit="g"),
        ],
    )
    dishes = {"P1": StubDish("P1", {"protein_g": 70.0})}
    day = analysis.analyse_day(
        "2026-03-01", [{"meal": "lunch", "dish_id": "P1"}], envelope, dishes
    )
    rows = {(r["nutrient"], r["kind"]): r for r in day["nutrients"]}
    assert len(rows) == 2
    assert rows[("protein_g", "max")]["status"] == "hard_violation"
    assert rows[("protein_g", "min")]["status"] == "ok"


def test_slope_uses_elapsed_days_not_indices() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg")],
    )
    dishes = {
        f"S{i}": StubDish(f"S{i}", {"sodium_mg": sodium})
        for i, sodium in enumerate([1050.0, 1100.0, 1150.0])
    }
    logs = _logs(
        "P0001",
        [("2026-01-01", "S0"), ("2026-01-11", "S1"), ("2026-01-21", "S2")],
    )
    logs = _complete_logs(logs, dishes)

    result = analysis.analyse_patient(logs, envelope, dishes)
    points = result["series"]["sodium_mg"]["points"]
    assert [p["exposure"] for p in points] == pytest.approx([5.0, 10.0, 15.0])

    assert result["flags"] == []

    flags = analysis.trend_flags(result["series"], slope_trigger=0.3)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["direction"] == "worsening"
    assert flag["slope_pct_per_day"] == pytest.approx(0.5)
    assert flag["projected_3d_exposure_pct"] == pytest.approx(16.5)


def test_slope_uneven_spacing_is_a_true_per_day_rate() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg")],
    )
    dishes = {f"S{i}": StubDish(f"S{i}", {"sodium_mg": 1000.0 + 50.0 * (i + 1)}) for i in range(3)}
    logs = _logs(
        "P0001",
        [("2026-01-01", "S0"), ("2026-01-02", "S1"), ("2026-01-04", "S2")],
    )
    logs = _complete_logs(logs, dishes)
    result = analysis.analyse_patient(logs, envelope, dishes)
    flags = analysis.trend_flags(result["series"], slope_trigger=0.1)
    assert flags[0]["slope_pct_per_day"] == pytest.approx(10.0 / 3.0, abs=1e-3)


def _category_exclusion(value: str) -> ExclusionFlag:
    return ExclusionFlag(
        kind=ExclusionKind.DISH_CATEGORY,
        value=value,
        reason=f"test exclusion: {value}",
        citation=_CITATION,
    )


def test_excluded_dish_is_hard_violation_even_with_ok_nutrients() -> None:
    envelope = _envelope(
        "P0001",
        [
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100_000.0, unit="mg"),
        ],
        exclusions=[_category_exclusion("deep_fried")],
    )
    dishes = {"D1": StubDish("D1", {"sodium_mg": 50.0}, category="deep_fried")}
    day = analysis.analyse_day(
        "2026-03-01", [{"meal": "dinner", "dish_id": "D1"}], envelope, dishes
    )
    assert day["compliant"] is False
    assert day["hard_violations"] == [
        {
            "type": "excluded_dish",
            "dish_id": "D1",
            "dish_name": "D1",
            "meal": "dinner",
            "exclusion_kind": "dish_category",
            "exclusion_value": "deep_fried",
            "reason": "test exclusion: deep_fried",
        }
    ]
    assert day["nutrients"][0]["status"] == "ok"


def test_allowed_dish_with_no_exclusions_stays_compliant() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100_000.0, unit="mg")],
        exclusions=[_category_exclusion("deep_fried")],
    )
    dishes = {"D1": StubDish("D1", {"sodium_mg": 50.0}, category="soup")}
    day = analysis.analyse_day(
        "2026-03-01", [{"meal": "dinner", "dish_id": "D1"}], envelope, dishes
    )
    assert day["compliant"] is True
    assert day["hard_violations"] == []


def test_exclusion_violations_count_in_aggregate_days() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100_000.0, unit="mg")],
        exclusions=[_category_exclusion("deep_fried")],
    )
    dishes = {"D1": StubDish("D1", {"sodium_mg": 50.0}, category="deep_fried")}
    logs = _logs("P0001", [("2026-03-01", "D1"), ("2026-03-02", "D1")])
    result = analysis.analyse_range(logs, envelope, dishes)
    assert result["aggregate"]["hard_violation_days"] == 2
    assert result["aggregate"]["hard_violations_by_nutrient"] == {}
    assert result["aggregate"]["days_logged"] == 2


def test_day_completeness_counts_distinct_logged_meals() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100_000.0, unit="mg")],
    )
    dishes = {"A": StubDish("A", {}), "B": StubDish("B", {}), "C": StubDish("C", {})}
    full = analysis.analyse_day(
        "2026-03-01",
        [
            {"meal": "dinner", "dish_id": "C"},
            {"meal": "breakfast", "dish_id": "A"},
            {"meal": "lunch", "dish_id": "B"},
        ],
        envelope,
        dishes,
    )
    assert full["completeness"] == {"meals_logged": 3, "expected_meals": 3, "complete": True}

    partial = analysis.analyse_day(
        "2026-03-02", [{"meal": "breakfast", "dish_id": "A"}], envelope, dishes
    )
    assert partial["completeness"] == {"meals_logged": 1, "expected_meals": 3, "complete": False}

    dup = analysis.analyse_day(
        "2026-03-03",
        [{"meal": "lunch", "dish_id": "A"}, {"meal": "lunch", "dish_id": "B"}],
        envelope,
        dishes,
    )
    assert dup["completeness"] == {"meals_logged": 1, "expected_meals": 3, "complete": False}


def test_range_aggregate_reports_complete_days() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=100_000.0, unit="mg")],
    )
    dishes = {"A": StubDish("A", {})}
    logs = [
        {"patient_id": "P0001", "date": "2026-03-01", "meal": "breakfast", "dish_id": "A"},
        {"patient_id": "P0001", "date": "2026-03-01", "meal": "lunch", "dish_id": "A"},
        {"patient_id": "P0001", "date": "2026-03-01", "meal": "dinner", "dish_id": "A"},
        {"patient_id": "P0001", "date": "2026-03-02", "meal": "lunch", "dish_id": "A"},
    ]
    result = analysis.analyse_range(logs, envelope, dishes)
    assert result["aggregate"]["days_logged"] == 2
    assert result["aggregate"]["complete_days"] == 1
    assert result["aggregate"]["fraction_complete"] == pytest.approx(0.5)
    empty = analysis.analyse_range([], envelope, dishes)
    assert empty["aggregate"]["complete_days"] == 0
    assert empty["aggregate"]["fraction_complete"] == 0.0


def test_nutrient_rows_carry_ranked_contributors() -> None:
    envelope = _envelope(
        "P0001",
        [
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=900.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=30.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.POTASSIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg"),
        ],
    )
    dishes = {
        "A": StubDish("A", {"sodium_mg": 600.0, "fiber_g": 5.0}, name="Dish A"),
        "B": StubDish("B", {"sodium_mg": 300.0, "fiber_g": 15.0}, name="Dish B"),
        "C": StubDish("C", {"sodium_mg": 100.0, "fiber_g": 5.0}, name="Dish C"),
    }
    day = analysis.analyse_day(
        "2026-03-01",
        [
            {"meal": "breakfast", "dish_id": "A"},
            {"meal": "lunch", "dish_id": "B"},
            {"meal": "dinner", "dish_id": "C"},
        ],
        envelope,
        dishes,
    )
    rows = {(r["nutrient"], r["kind"]): r for r in day["nutrients"]}

    sodium = rows[("sodium_mg", "max")]
    assert sodium["status"] == "hard_violation"
    assert sodium["contributors"] == [
        {"dish_id": "A", "dish_name": "Dish A", "amount": 600.0, "pct_of_day_total": pytest.approx(60.0)},
        {"dish_id": "B", "dish_name": "Dish B", "amount": 300.0, "pct_of_day_total": pytest.approx(30.0)},
    ]

    fiber = rows[("fiber_g", "min")]
    assert fiber["status"] == "soft_gap"
    assert [c["dish_id"] for c in fiber["contributors"]] == ["A", "C"]
    assert [c["amount"] for c in fiber["contributors"]] == [5.0, 5.0]
    assert fiber["contributors"][0]["pct_of_day_total"] == pytest.approx(20.0)

    potassium = rows[("potassium_mg", "max")]
    assert potassium["status"] == "ok"
    assert len(potassium["contributors"]) == 2
    assert all(c["amount"] == 0.0 and c["pct_of_day_total"] == 0.0 for c in potassium["contributors"])


def test_day_rows_carry_envelope_identity() -> None:
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg")],
    )
    day = analysis.analyse_day(
        "2026-03-01", [{"meal": "lunch", "dish_id": "A"}], envelope, {"A": StubDish("A", {})}
    )
    assert day["envelope_id"] == envelope.envelope_id
    assert day["envelope_version"] == 1


def test_p0006_roasted_chicken_rice_excluded(client, _isolated_envelope_store) -> None:
    run = client.post("/rules/run", json={"patient_id": "P0006"})
    assert run.status_code == 200, run.text
    envelope = run.json()["envelope"]
    assert client.post(f"/envelopes/{envelope['envelope_id']}/approve", json={}).status_code == 200
    assert any(
        e["value"] == "high_glycaemic_load" or e["value"] == "high_potassium_foods"
        for e in envelope["exclusions"]
    )

    day = datetime.now(UTC).date().isoformat()
    logged = client.post(
        "/adherence/log",
        json={"patient_id": "P0006", "date": day, "meal": "lunch", "dish_id": "SG0002"},
    )
    assert logged.status_code == 201, logged.text

    resp = client.get("/adherence/P0006/summary", params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    day_row = body["days"][0]

    assert day_row["compliant"] is False
    exclusion_hits = [v for v in day_row["hard_violations"] if v.get("type") == "excluded_dish"]
    assert len(exclusion_hits) == 1
    hit = exclusion_hits[0]
    assert hit["dish_id"] == "SG0002"
    assert hit["dish_name"] == "Roasted Chicken Rice"
    assert hit["meal"] == "lunch"
    assert hit["exclusion_kind"] in {"dish_category", "diet_pattern"}
    assert hit["exclusion_value"] in {"high_glycaemic_load", "high_potassium_foods"}
    assert hit["reason"]

    assert body["aggregate"]["hard_violations_by_nutrient"] == {}
    assert body["aggregate"]["hard_violation_days"] == 1
