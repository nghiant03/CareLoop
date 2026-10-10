"""Patient-aware swaps and isolated clinician what-if simulations.

Covers:

* ``GET /mining/substitutions?...&patient_id=`` — P0006 exclusion filtering,
  hard-check validation and
  day deltas; generic requests without patient_id omit validation metadata;
  ``plan_context_required`` 409 when the patient has no saved plan.
* ``POST /mining/swaps/apply`` — a valid swap saves a NEW plan row with
  ``derived_from`` lineage and leaves the source plan untouched; a
  MAX-ceiling-breaking swap and an excluded replacement both answer 422
  ``swap_violates_constraints`` without persisting anything.
* ``POST /simulations`` — the what-if comparison (base vs simulated), the
  read-only guarantee (envelope store, journal and latest saved plan are
  untouched), infeasible simulated targets, and a restart-style re-read of
  the simulation store.
"""

from __future__ import annotations

import pytest

from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE, find_latest_envelope_for_patient
from backend.optim.problem import exclusion_for
from backend.optim.real_data import load_dishes

# Attach simulations only when the imported app omits its route; normal
# application imports already mount it.
from backend.app.main import app as _app

if not any(getattr(route, "path", None) == "/simulations" for route in _app.routes):
    from backend.app.api import simulations as _simulations

    _app.include_router(_simulations.router)


# ---------------------------------------------------------------------------
# Shared setup (one solve per patient per module)
# ---------------------------------------------------------------------------


def _approve_and_plan(client, patient_id: str) -> dict:
    """Approve and plan; return an envelope_id/plan wrapper."""
    rules = client.post("/rules/run", json={"patient_id": patient_id})
    assert rules.status_code == 200, rules.text
    envelope_id = rules.json()["envelope"]["envelope_id"]
    approved = client.post(
        f"/envelopes/{envelope_id}/approve",
        json={"clinician_id": "dr-tan", "note": "swaps/what-if test"},
    )
    assert approved.status_code == 200, approved.text
    plan_resp = client.post("/plans", json={"patient_id": patient_id})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    assert plan["feasible"] is True, plan.get("infeasibility_reason")
    assert plan["plan_id"], "generated plan must be persisted with an id"
    return {"envelope_id": envelope_id, "plan": plan}


@pytest.fixture(scope="module")
def p0006(client):
    return _approve_and_plan(client, "P0006")


@pytest.fixture(scope="module")
def p0001(client):
    return _approve_and_plan(client, "P0001")


# ---------------------------------------------------------------------------
# 1. Patient-aware substitutions
# ---------------------------------------------------------------------------


def test_p0006_regression_excluded_candidate_never_recommended(client, p0006) -> None:
    """Returned candidates pass whole-day hard checks and carry nutrient deltas.

    The forced SG0009 -> SG0030 ranking precondition is covered separately in
    test_downstream_audit_regressions; this case exercises real endpoint ranking.
    """
    source, _ = _first_valid_swap(client, p0006["plan"])
    resp = client.get(
        "/mining/substitutions",
        params={"dish_id": source, "k": 3, "patient_id": "P0006", "plan_id": p0006["plan"]["plan_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["dish_id"] == source and body["k"] == 3
    assert body["patient_id"] == "P0006"
    assert body["plan_id"] == p0006["plan"]["plan_id"]
    assert body["informational_only"] is False
    assert body["notice"] is None

    suggestions = body["substitutions"]
    assert suggestions, "expected at least one validated substitution"
    assert "SG0030" not in [s["dish_id"] for s in suggestions], (
        "SG0030 Curry Mee is excluded by P0006's envelope and must never be "
        "recommended"
    )
    affected = {str(day) for day in body["affected_days"]}
    for item in suggestions:
        assert item["passes_hard_checks"] is True
        assert "day_deltas" in item
        assert set(item["day_deltas"]) == affected
        for deltas in item["day_deltas"].values():
            assert set(deltas) == {
                "energy_kcal", "protein_g", "sodium_mg", "potassium_mg",
                "phosphorus_mg", "carbs_g", "fat_g", "sat_fat_g",
                "fiber_g", "sugar_g",
            }
        assert isinstance(item["cost_delta"], (int, float))


def test_substitutions_without_patient_id_is_unchanged(client) -> None:
    """Legacy response shape: no validation fields, no persistence access."""
    resp = client.get("/mining/substitutions", params={"dish_id": "SG0009", "k": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"dish_id", "k", "substitutions"}
    for item in body["substitutions"]:
        assert set(item) == {
            "dish_id", "name", "distance", "nutrient_distance",
            "category_match", "reason", "ranking_score",
        }
        assert item["ranking_score"] == item["distance"]


def test_substitutions_patient_without_plan_409(client) -> None:
    """Envelope exists but no saved plan -> 409 plan_context_required."""
    rules = client.post("/rules/run", json={"patient_id": "P0005"})
    assert rules.status_code == 200, rules.text
    resp = client.get(
        "/mining/substitutions",
        params={"dish_id": "SG0009", "k": 3, "patient_id": "P0005"},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_context_required"
    assert "Generate a meal plan" in detail["message"]


# ---------------------------------------------------------------------------
# 2. Applying swaps
# ---------------------------------------------------------------------------


def _first_valid_swap(client, plan) -> tuple[str, str] | None:
    """First validated pair for the supplied immutable plan, not the latest plan."""
    patient_id = persistence.get_plan(plan["plan_id"])["patient_id"]
    seen: set[str] = set()
    for day in plan["days"]:
        for slot in day["slots"]:
            dish_id = slot["dish_id"]
            if dish_id in seen:
                continue
            seen.add(dish_id)
            resp = client.get(
                "/mining/substitutions",
                params={"dish_id": dish_id, "k": 1, "patient_id": patient_id, "plan_id": plan["plan_id"]},
            )
            assert resp.status_code == 200, resp.text
            suggestions = resp.json()["substitutions"]
            if suggestions:
                return dish_id, suggestions[0]["dish_id"]
    return None


def test_apply_valid_swap_creates_new_plan_with_lineage(client, p0006) -> None:
    plan = p0006["plan"]
    swap = _first_valid_swap(client, plan)
    assert swap is not None, "expected at least one valid swap for the plan"
    dish_id, replacement = swap

    resp = client.post(
        "/mining/swaps/apply",
        json={
            "patient_id": "P0006",
            "dish_id": dish_id,
            "replacement_dish_id": replacement,
            "plan_id": plan["plan_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    new_plan = resp.json()

    assert new_plan["plan_id"] != plan["plan_id"]
    assert new_plan["derived_from"] == plan["plan_id"]
    assert new_plan["applied_swap"]["dish_id"] == dish_id
    assert new_plan["applied_swap"]["replacement_dish_id"] == replacement
    assert new_plan["feasible"] is True and new_plan["violation_count"] == 0

    # Fetchable through the normal plan endpoint, source plan untouched.
    fetched = client.get(f"/plans/{new_plan['plan_id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["days"] == new_plan["days"]
    original = client.get(f"/plans/{plan['plan_id']}")
    assert original.status_code == 200, original.text
    assert original.json()["days"] == plan["days"]

    # The day the swap touched actually changed.
    assert new_plan["days"] != plan["days"]


def test_apply_swap_breaking_max_ceiling_422(client, p0006) -> None:
    """A swap whose replacement pushes a day past a hard MAX -> 422 and no
    new plan row."""
    envelope = find_latest_envelope_for_patient("P0006")
    assert envelope is not None
    dishes = load_dishes()
    lookup = {d.dish_id: d for d in dishes}
    allowed = [d for d in dishes if exclusion_for(d, envelope) is None]
    plan = p0006["plan"]

    found = None
    for day in plan["days"]:
        slot_ids = [slot["dish_id"] for slot in day["slots"]]
        for constraint in envelope.targets:
            if constraint.kind.value != "max":
                continue
            key = constraint.nutrient.value
            total = sum(lookup[d].nutrient(key) for d in slot_ids)
            headroom = constraint.value - total
            if headroom <= 0:
                continue
            for source in dict.fromkeys(slot_ids):
                needed = headroom + lookup[source].nutrient(key)
                best = max(
                    (d for d in allowed if d.dish_id != source),
                    key=lambda d: d.nutrient(key),
                )
                if best.nutrient(key) > needed + 1e-9:
                    found = (source, best.dish_id)
                    break
            if found:
                break
        if found:
            break
    assert found is not None, "test data must contain a ceiling-breaking swap"
    source, replacement = found

    plans_before = persistence.list_plans("P0006")
    resp = client.post(
        "/mining/swaps/apply",
        json={
            "patient_id": "P0006",
            "dish_id": source,
            "replacement_dish_id": replacement,
            "plan_id": plan["plan_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "swap_violates_constraints"
    assert detail["violations"]
    assert any(
        str(v.get("type", "")).startswith("max") for v in detail["violations"]
    ), detail["violations"]
    assert persistence.list_plans("P0006") == plans_before


def test_apply_swap_with_excluded_replacement_422(client, p0006) -> None:
    """An excluded replacement never lands in the plan -> 422 (exclusion)."""
    envelope = find_latest_envelope_for_patient("P0006")
    assert envelope is not None
    excluded = [
        d.dish_id for d in load_dishes() if exclusion_for(d, envelope) is not None
    ]
    assert excluded, "P0006's envelope must exclude something"
    source = p0006["plan"]["days"][0]["slots"][0]["dish_id"]
    replacement = next(d for d in excluded if d != source)

    plans_before = persistence.list_plans("P0006")
    resp = client.post(
        "/mining/swaps/apply",
        json={
            "patient_id": "P0006",
            "dish_id": source,
            "replacement_dish_id": replacement,
            "plan_id": p0006["plan"]["plan_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "swap_violates_constraints"
    assert any(v.get("type") == "exclusion" for v in detail["violations"])
    assert persistence.list_plans("P0006") == plans_before


# ---------------------------------------------------------------------------
# 3. Clinician what-if simulations
# ---------------------------------------------------------------------------


def _targets_with_sodium_max(value: float) -> list[dict]:
    """The approved P0001 targets with the sodium ceiling set to ``value``."""
    envelope = find_latest_envelope_for_patient("P0001")
    assert envelope is not None
    targets = [
        {
            "nutrient": t.nutrient.value,
            "kind": t.kind.value,
            "value": t.value,
            "unit": t.unit,
        }
        for t in envelope.targets
        if t.nutrient.value != "sodium_mg"
    ]
    targets.append({"nutrient": "sodium_mg", "kind": "max", "value": value, "unit": "mg"})
    return targets


def test_whatif_comparison_is_read_only_and_persisted(client, p0001) -> None:
    envelope_ids_before = sorted(ENVELOPE_STORE)
    latest_plan_before = persistence.latest_plan_for_patient("P0001")
    plans_before = persistence.list_plans("P0001")
    journal_before = persistence.list_envelope_history("P0001")

    resp = client.post(
        "/simulations",
        json={"patient_id": "P0001", "targets": _targets_with_sodium_max(1800.0)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["simulation_id"]
    assert body["base"]["envelope_id"] == p0001["envelope_id"]
    assert body["base"]["plan_id"] == p0001["plan"]["plan_id"]
    assert body["base"]["feasible"] is True
    assert body["base"]["objectives"]
    assert set(body["base"]["objectives"]) == {
        "nutrient_target_deviation", "preference_fit", "variety", "cost",
    }
    assert body["base"]["adequacy_summary"]

    simulated = body["simulated"]
    assert simulated["envelope_id"].startswith("SIM-")
    assert simulated["plan_id"] is None  # simulations never create plan rows
    assert simulated["feasible"] is True, simulated.get("infeasibility_reason")
    assert simulated["adequacy_summary"]  # scored vs the SIMULATED aims

    deltas = body["deltas"]
    assert set(deltas) == {
        "cost", "nutrient_target_deviation", "variety",
        "worst_shortfall_pct", "meals_changed",
    }
    assert all(value is not None for value in deltas.values())
    assert isinstance(deltas["meals_changed"], int) and deltas["meals_changed"] >= 0

    # Read-only guarantee: live state is untouched by the simulation.
    assert sorted(ENVELOPE_STORE) == envelope_ids_before
    assert persistence.latest_plan_for_patient("P0001") == latest_plan_before
    assert persistence.list_plans("P0001") == plans_before
    assert persistence.list_envelope_history("P0001") == journal_before

    listed = client.get("/simulations", params={"patient_id": "P0001"})
    assert listed.status_code == 200, listed.text
    listing = listed.json()
    assert listing["count"] >= 1
    stored = next(
        s for s in listing["simulations"] if s["simulation_id"] == body["simulation_id"]
    )
    assert stored["base_envelope_id"] == p0001["envelope_id"]
    assert stored["proposed_targets"] == body["proposed_targets"]
    assert stored["comparison"]["simulated"]["envelope_id"] == simulated["envelope_id"]


def test_whatif_infeasible_targets_still_reported(client, p0001) -> None:
    """A provably impossible target set answers 200 with infeasibility
    reporting instead of raising; the live state stays untouched."""
    plans_before = persistence.list_plans("P0001")
    resp = client.post(
        "/simulations",
        json={"patient_id": "P0001", "targets": _targets_with_sodium_max(2.0)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["simulated"]["feasible"] is False
    assert body["simulated"]["infeasibility_reason"]
    assert body["deltas"]["meals_changed"] is None
    assert body["deltas"]["cost"] is None
    assert persistence.list_plans("P0001") == plans_before


def test_simulation_store_survives_fresh_handle(client, p0001) -> None:
    """Restart-style read: a fresh sqlite handle (each persistence call opens
    its own connection) still lists the stored simulation."""
    persistence.init_db()
    rows = persistence.list_simulations("P0001")
    assert rows, "stored simulations must survive a fresh handle"
    for row in rows:
        assert row["simulation_id"]
        assert row["base_envelope_id"]
        assert row["comparison"] is not None
        assert row["proposed_targets"]
