from copy import deepcopy
from decimal import Decimal

from test_logging import PATIENT
from test_patients import CLINICIAN
from test_planning import approve_plan, food, ready, request

from careloop.planning.checker import check_plan


def setup(client):
    p, target = ready(client)
    foods = [
        food(
            client,
            str(i),
            nutrients={"energy": 330, "sodium": 100, "protein": 10, "carbohydrate": 50, "fat": 10},
        )
        for i in range(3)
    ]
    result = request(client, target, foods, days=2, items_per_slot={"breakfast": 2, "lunch": 3})
    plan = result["alternatives"][0]
    assert plan["body"]["check"]["valid"], plan["body"]["check"]
    assert approve_plan(client, plan).status_code == 200
    return p, target, foods, plan


def test_multi_item_search_coverage_totals_and_mandatory_checks(client):
    p, target, _, plan = setup(client)
    meals = plan["body"]["meals"]
    assert len(meals) == 12
    lunch = [m for m in meals if m["day"] == 1 and m["slot"] == "lunch"]
    assert {m["item"] for m in lunch} == {1, 2, 3}
    assert len({m["food_id"] for m in lunch}) == 3
    check = plan["body"]["check"]
    for day in (1, 2):
        total = sum(Decimal(m["quantity"]) * Decimal("3.3") for m in meals if m["day"] == day)
        assert Decimal(check["daily_totals"][str(day)]["energy"]) == total
        assert sum(Decimal(v["energy"]) for v in check["meal_totals"][str(day)].values()) == total
    for modified in (meals[:-1], meals + [meals[-1]]):
        assert not check_plan(
            modified,
            2,
            plan["request"]["schedule"],
            p["body"]["facts"],
            target["body"]["items"],
            plan["request"]["items_per_slot"],
        )["valid"]
    changed = deepcopy(meals)
    changed[1]["food"]["allergen_status"]["milk"] = "present"
    result = check_plan(
        changed,
        2,
        plan["request"]["schedule"],
        {**p["body"]["facts"], "allergies": ["milk"]},
        target["body"]["items"],
        plan["request"]["items_per_slot"],
    )
    assert not result["valid"]


def test_item_substitution_recommendation_and_sibling_preservation(client):
    _, _, _, plan = setup(client)
    replacement = food(
        client,
        "replacement",
        nutrients={"energy": 330, "sodium": 100, "protein": 10, "carbohydrate": 50, "fat": 10},
    )
    selected = next(
        m for m in plan["body"]["meals"] if (m["day"], m["slot"], m["item"]) == (1, "lunch", 2)
    )
    response = client.post(
        f"/api/plans/{plan['id']}/substitution-recommendations",
        json={**CLINICIAN, "day": 1, "slot": "lunch", "item": 2, "food_ids": [replacement["id"]]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recommendations"][0]["substitution"]["item"] == 2
    draft = client.post(
        f"/api/plans/{plan['id']}/substitutions",
        json={
            **CLINICIAN,
            "day": 1,
            "slot": "lunch",
            "item": 2,
            "food_id": replacement["id"],
            "portion_id": "serving",
            "scale": selected["scale"],
        },
    )
    assert draft.status_code == 201, draft.text
    for before, after in zip(plan["body"]["meals"], draft.json()["body"]["meals"], strict=True):
        if before == selected:
            assert after["food_id"] == replacement["id"]
        else:
            assert before == after
    assert approve_plan(client, draft.json()).status_code == 200


def test_item_logs_and_atomic_whole_meal_confirmation(client):
    p, _, _, plan = setup(client)
    base = f"/api/patients/{p['id']}"
    data = {**PATIENT, "logged_on": "2026-11-01", "slot": "lunch", "plan_id": plan["id"]}
    one = client.post(base + "/meal-logs", json={**data, "item": 2, "status": "skipped"})
    assert one.status_code == 201, one.text
    # Item 2's conflict must roll back item 1's insertion.
    assert client.post(base + "/meal-log-confirmations", json=data).status_code == 409
    summary = client.get(base + "/meal-log-days/2026-11-01", params={"plan_id": plan["id"]}).json()
    assert len(summary["entries"]) == 1
    assert {(s["item"], s["status"]) for s in summary["planned_slots"] if s["slot"] == "lunch"} == {
        (1, "unlogged"),
        (2, "skipped"),
        (3, "unlogged"),
    }
    confirmed = client.post(base + "/meal-log-confirmations", json={**data, "slot": "breakfast"})
    assert confirmed.status_code == 201 and len(confirmed.json()) == 2
    correction = client.post(
        base + f"/meal-logs/{one.json()['id']}/revisions",
        json={**data, "item": 3, "status": "as_planned", "expected_revision": 1},
    )
    assert correction.status_code == 422


def test_item_counts_require_enough_foods_and_valid_slots(client):
    _, target = ready(client)
    result = request(client, target, [food(client)], items_per_slot={"lunch": 2})
    assert result["outcome"]["status"] == "blocked"
    assert "distinct eligible" in str(result["outcome"]["blockers"])
