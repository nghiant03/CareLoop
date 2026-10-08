"""Adherence analysis semantics — regression coverage.

Covers four correctness properties of :mod:`backend.app.adherence.analysis`
beyond the endpoint-level tests in ``test_adherence.py``:

* ``MIN`` exposure measures **shortfall below the floor** and grows as
  intake falls further under the limit, so a shrinking-fibre week trends
  ``worsening``;
* a nutrient constrained on **both** sides (MIN + MAX band) gets one
  deviation series per constraint — correct limit and direction each, one
  point per date per series — while single-constraint nutrients keep the
  plain nutrient key;
* trend slopes are computed against **elapsed days** between observation
  dates, not observation indices (three sodium readings 10 days apart
  rising 5 -> 10 -> 15 % yield 0.5 pct-points/day, not 5);
* the envelope's hard **exclusions** are enforced per logged dish in
  ``analyse_day``: a dish hit by an exclusion flag is a hard violation even
  when every nutrient ceiling is respected (reproduced end-to-end for the
  real P0006 envelope and SG0002 Roasted Chicken Rice).

Series/flags use the analysis layer directly with stub dishes for exact
math; the exclusion case additionally goes through the FastAPI app with the
real rules-engine envelope and dish dataset.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

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

from backend.app.main import app


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_meal_logs():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def _isolated_envelope_store():
    """Snapshot the process-global envelope store around each test."""
    snapshot = dict(ENVELOPE_STORE)
    yield
    ENVELOPE_STORE.clear()
    ENVELOPE_STORE.update(snapshot)


class StubDish:
    """Minimal dish stand-in: exact nutrients, no exclusions unless stated."""

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
    """One lunch log per (date, dish_id) pair."""
    return [
        {"patient_id": patient_id, "date": day, "meal": "lunch", "dish_id": dish_id}
        for day, dish_id in days_and_dishes
    ]


_CITATION = CitationSource(
    guideline="Test Guideline", section="1.0", rule_id="R-TEST"
)


# ---------------------------------------------------------------------------
# 1. MIN exposure = shortfall below the floor, and it trends
# ---------------------------------------------------------------------------


def test_min_shortfall_exposure_rises_and_flags_worsening() -> None:
    """Fibre MIN 25 g with intake 20 -> 15 -> 10 g: exposure 20 -> 40 -> 60 %.

    The exposure must measure the shortfall relative to the floor (and hence
    grow as intake drops), and the rising series must be flagged worsening.
    """
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

    result = analysis.analyse_patient(logs, envelope, dishes)
    series = result["series"]["fiber_g"]
    assert series["kind"] == "min"
    assert series["limit"] == 25.0
    assert [p["total"] for p in series["points"]] == [20.0, 15.0, 10.0]
    assert [p["exposure"] for p in series["points"]] == pytest.approx([20.0, 40.0, 60.0])
    # signed pct stays signed: below the floor is negative
    assert [p["pct"] for p in series["points"]] == pytest.approx([-20.0, -40.0, -60.0])

    flags = result["flags"]
    assert len(flags) == 1
    flag = flags[0]
    assert flag["nutrient"] == "fiber_g"
    assert flag["kind"] == "min"
    assert flag["direction"] == "worsening"
    assert flag["slope_pct_per_day"] == pytest.approx(20.0)
    assert flag["severity"] == "alert"  # latest 60 % >= 25 % alert threshold
    # per-day projection on the same time base: 60 + 3 * 20 = 120
    assert flag["projected_3d_exposure_pct"] == pytest.approx(120.0)


def test_min_satisfied_day_has_zero_exposure() -> None:
    """Meeting the floor is zero exposure (no inversion into the MAX branch)."""
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


# ---------------------------------------------------------------------------
# 2. MIN + MAX band: one series per constraint, correct limit/direction each
# ---------------------------------------------------------------------------


def test_band_nutrient_gets_one_series_per_constraint() -> None:
    """Protein MIN 50 / MAX 60: two series, each with its own limit and
    direction, exactly one point per date per series. A single-constraint
    nutrient (sodium MAX) keeps the plain nutrient key."""
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

    # single-constraint nutrient: unchanged plain key
    assert set(series) == {"protein_g:min", "protein_g:max", "sodium_mg"}
    assert series["sodium_mg"]["kind"] == "max"
    assert series["sodium_mg"]["limit"] == 1000.0

    min_series = series["protein_g:min"]
    max_series = series["protein_g:max"]
    assert min_series["kind"] == "min"
    assert min_series["limit"] == 50.0
    assert max_series["kind"] == "max"
    assert max_series["limit"] == 60.0

    # one point per date per series, in chronological order
    for s in (min_series, max_series, series["sodium_mg"]):
        assert [p["date"] for p in s["points"]] == days

    # day 1 (55 g): inside the band -> zero exposure on both sides
    assert min_series["points"][0]["exposure"] == 0.0
    assert max_series["points"][0]["exposure"] == 0.0
    # day 2 (70 g): above the MAX -> excess exposure on the MAX side only;
    # the MIN side stays satisfied (0 exposure, not nonsense reusing 60).
    assert max_series["points"][1]["exposure"] == pytest.approx(
        (70.0 - 60.0) / 60.0 * 100.0, abs=1e-3
    )
    assert min_series["points"][1]["exposure"] == 0.0
    # MIN limit is actually used on the MIN side: 40 g would be a 20 % shortfall
    under = analysis.deviation_series(
        [{"date": "2026-03-03", "totals": {"protein_g": 40.0}}], envelope
    )
    assert under["protein_g:min"]["points"][0]["exposure"] == pytest.approx(20.0)
    assert under["protein_g:max"]["points"][0]["exposure"] == 0.0


def test_band_nutrient_soft_gap_rows_per_constraint() -> None:
    """Day rows classify each band side independently (MIN under, MAX over)."""
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


# ---------------------------------------------------------------------------
# 3. Trend slopes use elapsed days, not observation indices
# ---------------------------------------------------------------------------


def test_slope_uses_elapsed_days_not_indices() -> None:
    """Sodium readings 10 days apart rising 5 -> 10 -> 15 %: the per-day
    slope is 0.5 pct-points/day. With the index-based slope this would have
    been 5 pct-points/day and (wrongly) tripped the default trigger."""
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg")],
    )
    dishes = {
        f"S{i}": StubDish(f"S{i}", {"sodium_mg": sodium})
        for i, sodium in enumerate([1050.0, 1100.0, 1150.0])
    }
    # observations 10 days apart
    logs = _logs(
        "P0001",
        [("2026-01-01", "S0"), ("2026-01-11", "S1"), ("2026-01-21", "S2")],
    )

    result = analysis.analyse_patient(logs, envelope, dishes)
    points = result["series"]["sodium_mg"]["points"]
    assert [p["exposure"] for p in points] == pytest.approx([5.0, 10.0, 15.0])

    # 0.5 pct-points/day is a slow drift: no flag at the default trigger
    assert result["flags"] == []

    # lowering the trigger exposes the exact per-day slope
    flags = analysis.trend_flags(result["series"], slope_trigger=0.3)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["direction"] == "worsening"
    assert flag["slope_pct_per_day"] == pytest.approx(0.5)
    # 3-day projection on the same (per-day) time base: 15 + 3 * 0.5 = 16.5
    assert flag["projected_3d_exposure_pct"] == pytest.approx(16.5)


def test_slope_uneven_spacing_is_a_true_per_day_rate() -> None:
    """1 -> 2 -> 3 days spacing: Theil-Sen over elapsed days, not indices."""
    envelope = _envelope(
        "P0001",
        [NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=1000.0, unit="mg")],
    )
    dishes = {f"S{i}": StubDish(f"S{i}", {"sodium_mg": 1000.0 + 50.0 * (i + 1)}) for i in range(3)}
    logs = _logs(
        "P0001",
        [("2026-01-01", "S0"), ("2026-01-02", "S1"), ("2026-01-04", "S2")],
    )
    result = analysis.analyse_patient(logs, envelope, dishes)
    flags = analysis.trend_flags(result["series"], slope_trigger=0.1)
    # pairwise slopes: 5/1, 5/2, 10/3 -> median 10/3 (rounded to 4 dp)
    assert flags[0]["slope_pct_per_day"] == pytest.approx(10.0 / 3.0, abs=1e-3)


# ---------------------------------------------------------------------------
# 4. Envelope exclusions are hard constraints in the day analysis
# ---------------------------------------------------------------------------


def _category_exclusion(value: str) -> ExclusionFlag:
    return ExclusionFlag(
        kind=ExclusionKind.DISH_CATEGORY,
        value=value,
        reason=f"test exclusion: {value}",
        citation=_CITATION,
    )


def test_excluded_dish_is_hard_violation_even_with_ok_nutrients() -> None:
    """A dish hit by an envelope exclusion is a hard violation regardless of
    its nutrient totals; compliant flips to False."""
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
    # the nutrient row itself is still "ok" — the exclusion is the violation
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
    """Exclusion violations drive ``hard_violation_days`` but are dish-scoped,
    so ``hard_violations_by_nutrient`` stays empty for them."""
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


# ---------------------------------------------------------------------------
# End-to-end: the real P0006 envelope excludes SG0002 Roasted Chicken Rice
# ---------------------------------------------------------------------------


def test_p0006_roasted_chicken_rice_excluded(client, _isolated_envelope_store) -> None:
    """P0006's rules-engine envelope excludes SG0002 (high-glycaemic-load /
    high-potassium semantic mappings). Logging it must yield compliant=False
    with a hard violation naming the dish and the exclusion — even though
    every nutrient total stays under its ceiling."""
    run = client.post("/rules/run", json={"patient_id": "P0006"})
    assert run.status_code == 200, run.text
    envelope = run.json()["envelope"]
    assert any(
        e["value"] == "high_glycaemic_load" or e["value"] == "high_potassium_foods"
        for e in envelope["exclusions"]
    )

    day = (date.today()).isoformat()
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

    # SG0002's nutrients alone stay under P0006's ceilings: no nutrient-side
    # hard violations, only the exclusion.
    assert body["aggregate"]["hard_violations_by_nutrient"] == {}
    assert body["aggregate"]["hard_violation_days"] == 1