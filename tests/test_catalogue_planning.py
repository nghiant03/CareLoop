from types import SimpleNamespace

from test_planning import PATIENT, approve_plan, food, ready, request

from careloop.planning.search import generate


def payload(target, **changes):
    return {
        **PATIENT,
        "target_id": target["id"],
        "target_revision": target["latest_revision"],
        "start_date": "2026-11-01",
        "days": 1,
        "schedule": ["breakfast", "lunch", "dinner"],
        **changes,
    }


def test_catalogue_default_checks_all_records_and_pins_pool_revisions(client):
    _, target = ready(client)
    for i in range(101):
        food(client, str(i), nutrients={"energy": 330})
    good = food(client, "complete")
    result = client.post("/api/plan-requests", json=payload(target))
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["outcome"]["pool_mode"] == "catalogue"
    assert body["outcome"]["pool_food_count"] == 102
    assert body["outcome"]["eligible_food_count"] == 1
    assert len(body["outcome"]["excluded_foods"]) == 101
    plan = body["alternatives"][0]
    assert plan["body"]["check"]["valid"]
    assert all(m["food_id"] == good["id"] for m in plan["body"]["meals"])
    assert len(plan["request"]["food_pool_revisions"]) == 102
    assert approve_plan(client, plan).status_code == 200


def test_catalogue_exclusions_and_allergies_are_enforced(client):
    _, target = ready(client, allergies=["milk"])
    safe = food(client, "safe", allergen_status={"milk": "absent"})
    unsafe = food(client, "unsafe", allergen_status={"milk": "present"})
    excluded = food(client, "excluded", allergen_status={"milk": "absent"})
    response = client.post(
        "/api/plan-requests", json=payload(target, excluded_food_ids=[excluded["id"]])
    )
    assert response.status_code == 201
    result = response.json()
    assert result["outcome"]["pool_food_count"] == 2
    assert result["outcome"]["excluded_foods"][0]["food_id"] == unsafe["id"]
    assert all(m["food_id"] == safe["id"] for m in result["alternatives"][0]["body"]["meals"])
    for overrides in (
        {"food_ids": []},
        {"excluded_food_ids": [safe["id"], safe["id"]]},
        {"food_ids": [safe["id"]], "excluded_food_ids": [safe["id"]]},
    ):
        assert (
            client.post("/api/plan-requests", json=payload(target, **overrides)).status_code == 422
        )
    # An explicit pool retains its meaning and never silently expands to the catalogue.
    custom = client.post("/api/plan-requests", json=payload(target, food_ids=[unsafe["id"]])).json()
    assert custom["outcome"]["status"] == "blocked"
    assert not custom["alternatives"]


def test_empty_catalogue_returns_clear_blockers(client):
    _, target = ready(client)
    response = client.post("/api/plan-requests", json=payload(target))
    assert response.status_code == 201
    result = response.json()
    assert result["outcome"]["status"] == "blocked"
    assert result["outcome"]["pool_food_count"] == 0
    assert not result["alternatives"]


def test_large_automatic_pool_is_shortlisted_deterministically_after_checks():
    from test_nutrition_constraints import FACTS, action, fixture

    rows = [
        {"id": f"f{i:03}", "latest_revision": 1, "body": fixture({"energy": 1000})["food"]}
        for i in range(180)
    ]
    req = SimpleNamespace(days=1, schedule=["lunch"], items_per_slot={"lunch": 3})
    items = [{"action": action("range", "energy", 1400, "kcal/day", upper=1600)}]
    plans, outcome = generate(rows, req, FACTS, items, automatic_pool=True, beam_width=1)
    assert outcome["shortlisted"]
    assert outcome["eligible_portion_counts"] == {"lunch": 540}
    assert outcome["searched_portion_counts"] == {"lunch": 500}
    assert len({m["food_id"] for m in plans[0]["meals"]}) == 3
    assert plans[0]["check"]["valid"]
    assert (
        generate(list(reversed(rows)), req, FACTS, items, automatic_pool=True, beam_width=1)[0]
        == plans
    )


def test_replacement_search_defaults_to_catalogue(client):
    _, target = ready(client)
    original = food(
        client,
        "original",
        nutrients={"energy": 330, "protein": 10, "carbohydrate": 30, "fat": 10, "sodium": 100},
    )
    plan = request(client, target, [original])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    replacement = food(client, "replacement", nutrients=original["body"]["nutrients"])
    response = client.post(
        f"/api/plans/{plan['id']}/substitution-recommendations",
        json={
            **PATIENT,
            "day": 1,
            "slot": "lunch",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["recommendations"][0]["food_id"] == replacement["id"]
