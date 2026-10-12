"""Plan adequacy tests.

Covers the top-level ``adequacy[]`` array on the plan response, scored against
the ORIGINAL clinician-approved envelope (not the relaxed copy the optimiser
solved):

* a relaxed MIN floor (fibre 25 g/d lowered to 24 g/d) with low actuals ->
  ``aim`` keeps the approved value, ``relaxed_aim`` exposes the solved floor,
  shortfall/shortfall_pct are positive, met_days/total_days are correct;
* a fully-met MIN -> zero shortfall, ``met_days == total_days``,
  ``relaxed_aim`` is null;
* an infeasible plan -> ``adequacy`` is empty;
* MAX ceilings are excluded and entries keep envelope order;
* the API response (``POST /plans``) carries the field through.

Unit tests use hand-built envelopes + a small dish pool (same ``Dish``
contract as ``backend.optim.toy_data``); the API test follows the
``test_e2e.py`` flow (rules -> approve -> plans).
"""

from __future__ import annotations

from backend.app.core.plan_service import map_plan_result, prepare_envelope_for_pool
from backend.optim.toy_data import Dish
from shared.envelope_schema import (
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


def _nut(fiber_g: float = 0.0, protein_g: float = 0.0, sodium_mg: float = 0.0) -> dict:
    return {
        "energy_kcal": 0.0,
        "protein_g": protein_g,
        "sodium_mg": sodium_mg,
        "potassium_mg": 0.0,
        "phosphorus_mg": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "sat_fat_g": 0.0,
        "fiber_g": fiber_g,
        "sugar_g": 0.0,
    }


def _dish(dish_id: str, **nutrients) -> Dish:
    return Dish(
        dish_id=dish_id,
        name=dish_id.replace("_", " ").title(),
        category="test",
        nutrients=_nut(**nutrients),
    )


def _envelope(patient_id: str, targets: list[NutrientConstraint]) -> NutrientEnvelope:
    return NutrientEnvelope(
        envelope_id=f"env-adequacy-{patient_id}",
        patient_id=patient_id,
        status=EnvelopeStatus.APPROVED,
        patient_snapshot=PatientSummary(
            patient_id=patient_id, age=60, sex="M", weight_kg=70.0
        ),
        targets=targets,
        priority_basis="test fixture: adequacy scoring",
    )


def _plan(days: list[list[list[str]]]) -> list[list[str]]:
    """Day-major flat slot list from per-day slot lists (3 meals per day)."""
    plan: list[list[str]] = []
    for day in days:
        assert len(day) == 3
        plan.extend(day)
    return plan


def _result(plan: list[list[str]], feasible: bool = True) -> dict:
    return {"feasible": feasible, "violation_count": 0, "plan": plan}


def _fiber_entry(adequacy: list[dict]) -> dict:
    return next(a for a in adequacy if a["nutrient"] == "fiber_g")


# ---------------------------------------------------------------------------
# (a) relaxed-fibre case
# ---------------------------------------------------------------------------


def test_relaxed_min_reports_original_aim_and_relaxed_floor() -> None:
    """Fibre MIN 25 g/d relaxed to 24 g/d (pool tops out at 8 g/dish):
    adequacy keeps aim 25, discloses relaxed_aim 24, and reports the
    shortfall against the ORIGINAL aim even though the plan fully meets
    the relaxed floor."""
    dishes = [_dish("fibre_ceiling", fiber_g=8.0)]
    envelope = _envelope(
        "adeq-a",
        [
            NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=25.0, unit="g"),
        ],
    )
    solved, relaxed = prepare_envelope_for_pool(envelope, dishes)
    assert relaxed and relaxed[0]["requested"] == 25.0 and relaxed[0]["relaxed_to"] == 24.0

    plan = _plan([[["fibre_ceiling"]] * 3] * 7)  # 24 g fibre/day = relaxed floor
    out = map_plan_result(_result(plan), envelope, dishes, relaxed_constraints=relaxed, solved_envelope=solved)

    assert out["feasible"] is True
    entry = _fiber_entry(out["adequacy"])
    assert entry == {
        "nutrient": "fiber_g",
        "kind": "min",
        "unit": "g",
        "aim": 25.0,
        "mean_daily": 24.0,
        "worst_day": 1,
        "worst_daily": 24.0,
        "shortfall": 1.0,
        "shortfall_pct": 4.0,
        "met_days": 0,
        "total_days": 7,
        "relaxed_aim": 24.0,
    }
    # The solved envelope is met every day, yet the approved aim is not:
    # exactly the blind spot adequacy closes.
    assert entry["met_days"] == 0 and entry["total_days"] == 7


# ---------------------------------------------------------------------------
# (b) fully-met MIN
# ---------------------------------------------------------------------------


def test_fully_met_min_has_zero_shortfall_and_no_relaxed_aim() -> None:
    dishes = [
        _dish("protein_low", protein_g=6.0),
        _dish("protein_mid", protein_g=7.0),
        _dish("protein_high", protein_g=10.0),
    ]
    envelope = _envelope(
        "adeq-b",
        [
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=20.0, unit="g"),
        ],
    )
    solved, relaxed = prepare_envelope_for_pool(envelope, dishes)
    assert relaxed == []  # 30 g/day achievable, nothing relaxed

    # Day 1 hits the aim exactly (7+7+6=20); day 2 overshoots (30).
    plan = _plan(
        [
            [["protein_mid"], ["protein_mid"], ["protein_low"]],
            [["protein_high"], ["protein_high"], ["protein_high"]],
        ]
        * 3
        + [
            [["protein_mid"], ["protein_mid"], ["protein_low"]],
        ]
    )
    out = map_plan_result(_result(plan), envelope, dishes, relaxed_constraints=relaxed, solved_envelope=solved)

    entry = next(a for a in out["adequacy"] if a["nutrient"] == "protein_g")
    assert entry["aim"] == 20.0
    assert entry["mean_daily"] == 24.286
    assert entry["worst_day"] == 1
    assert entry["worst_daily"] == 20.0
    assert entry["shortfall"] == 0.0
    assert entry["shortfall_pct"] == 0.0
    assert entry["met_days"] == entry["total_days"] == 7
    assert entry["relaxed_aim"] is None


# ---------------------------------------------------------------------------
# (c) infeasible plan -> empty adequacy
# ---------------------------------------------------------------------------


def test_infeasible_plan_has_empty_adequacy() -> None:
    dishes = [_dish("whatever", fiber_g=1.0)]
    envelope = _envelope(
        "adeq-c",
        [
            NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=25.0, unit="g"),
        ],
    )
    out = map_plan_result(_result([], feasible=False), envelope, dishes, relaxed_constraints=[])
    assert out["feasible"] is False
    assert out["days"] == []
    assert out["adequacy"] == []


# ---------------------------------------------------------------------------
# Ordering + MAX exclusion + per-day worst tracking
# ---------------------------------------------------------------------------


def test_adequacy_excludes_max_and_keeps_envelope_order() -> None:
    dishes = [
        _dish("mixed", fiber_g=1.0, protein_g=5.0, sodium_mg=900.0),
    ]
    envelope = _envelope(
        "adeq-order",
        [
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.FIBER_G, kind=ConstraintKind.MIN, value=10.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.TARGET, value=15.0, unit="g"),
        ],
    )
    # Day 1: 3 g fibre / 15 g protein; day 2: 4 g fibre / 20 g protein.
    plan = _plan(
        [
            [["mixed"], ["mixed"], ["mixed"]],
            [["mixed", "mixed"], ["mixed"], ["mixed"]],
        ]
    )
    out = map_plan_result(_result(plan), envelope, dishes)

    assert [a["nutrient"] for a in out["adequacy"]] == ["fiber_g", "protein_g"]
    fiber, protein = out["adequacy"]
    assert fiber["kind"] == "min" and protein["kind"] == "target"
    # Worst day is the LOWEST total (1-based index), not day 2.
    assert fiber["worst_day"] == 1 and fiber["worst_daily"] == 3.0
    assert fiber["mean_daily"] == 3.5
    assert protein["worst_day"] == 2 and protein["worst_daily"] == 20.0
    assert protein["mean_daily"] == 17.5
    assert protein["shortfall"] == 5.0 and protein["met_days"] == 1
    assert protein["total_days"] == 2


# ---------------------------------------------------------------------------
# API passthrough
# ---------------------------------------------------------------------------


def _run_rules(client, patient_id: str) -> dict:
    resp = client.post("/rules/run", json={"patient_id": patient_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_plan_response_includes_adequacy(client) -> None:
    body = _run_rules(client, "P0001")
    envelope_id = body["envelope"]["envelope_id"]
    approved = client.post(
        f"/envelopes/{envelope_id}/approve",
        json={"clinician_id": "dr-tan", "note": "adequacy test"},
    )
    assert approved.status_code == 200, approved.text

    resp = client.post("/plans", json={"patient_id": "P0001"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["feasible"] is True, plan.get("infeasibility_reason")

    adequacy = plan["adequacy"]
    assert isinstance(adequacy, list) and adequacy
    for entry in adequacy:
        assert set(entry) == {
            "nutrient",
            "kind",
            "unit",
            "aim",
            "mean_daily",
            "worst_day",
            "worst_daily",
            "shortfall",
            "shortfall_pct",
            "met_days",
            "total_days",
            "relaxed_aim",
        }
        assert entry["kind"] in ("min", "target")  # MAX ceilings excluded
        assert entry["total_days"] == 7
        assert 1 <= entry["worst_day"] <= 7
    # Composite (multi-dish) meals meet the original fibre floor on every
    # planned day, so adequacy reports no relaxed aim or shortfall.
    fiber = next(a for a in adequacy if a["nutrient"] == "fiber_g")
    assert fiber["relaxed_aim"] is None
    assert fiber["shortfall"] == fiber["shortfall_pct"] == 0
    assert fiber["met_days"] == fiber["total_days"]
