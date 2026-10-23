from decimal import Decimal

import pytest
from test_patients import CLINICIAN, REVIEWER
from test_planning import approve_plan, food, ready, request

from careloop.evaluate_foods import evaluate
from careloop.foods.clustering import fit, retrieve, vector


def composition(protein=10, carbohydrate=50, fat=10, energy=330, sodium=100):
    return {
        "protein": protein,
        "carbohydrate": carbohydrate,
        "fat": fat,
        "energy": energy,
        "sodium": sodium,
    }


def rows():
    return [
        {"id": key, "body": {"nutrients": nutrients, "category": category}}
        for key, nutrients, category in [
            ("a", composition(), "dish"),
            ("b", composition(protein=11), "dish"),
            ("c", composition(protein=0, carbohydrate=0, fat=100, energy=900), "oil"),
            ("d", composition(protein=0, carbohydrate=0, fat=99, energy=900), "oil"),
            ("e", composition(protein=None), "dish"),
        ]
    ]


def test_clusters_are_stable_separate_profiles_and_preserve_unknowns():
    data = rows()
    model = fit(data, 2)
    assert model == fit(list(reversed(data)), 2)
    labels = model["membership"]
    assert labels["a"] == labels["b"]
    assert labels["c"] == labels["d"] != labels["a"]
    assert model["excluded_food_ids"] == ["e"]
    assert [r["id"] for r, _ in retrieve(data, data[0], model, "cluster")] == ["b"]
    assert len(retrieve(data, data[0], model, "nearest")) == 3
    assert len(retrieve(data, data[0], model, "same_category")) == 2
    assert vector({"nutrients": composition(energy=0)}) is None
    assert vector({**data[0]["body"], "basis": "ml"}) == vector(data[0]["body"])


def fixture(client, **facts):
    p, target = ready(client, **facts)
    source = food(client, "source", nutrients=composition(), allergen_status={"milk": "absent"})
    plan = request(client, target, [source])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    return p, source, plan


def test_retrieval_pilot_reports_coverage_and_missing_feature_limits():
    report = evaluate(rows(), clusters=2, top=5)
    methods = report["methods"]
    assert methods["cluster"]["returned"] == 4
    assert methods["nearest"]["returned"] == 12
    assert methods["same_category"]["returned"] == 8
    assert methods["cluster"]["queries_with_results"] == 4
    assert methods["same_category"]["queries_with_results"] == 5
    assert methods["same_category"]["missing_distance_count"] == 4
    for method in methods.values():
        assert all(q["food_id"] not in q["returned_ids"] for q in method["query_results"])


def recommend(client, plan, foods, **changes):
    return client.post(
        f"/api/plans/{plan['id']}/substitution-recommendations",
        json={
            **CLINICIAN,
            "day": 1,
            "slot": "lunch",
            "food_ids": [f["id"] for f in foods],
            "clusters": 1,
            **changes,
        },
    )


@pytest.mark.parametrize("method", ["cluster", "nearest", "same_category"])
def test_checked_recommendations_differences_and_approval_workflow(client, method):
    _, source, plan = fixture(client, dislikes=["Disliked"])
    liked = food(client, "liked", nutrients=composition())
    disliked = food(client, "disliked", name="Disliked dish", nutrients=composition())
    response = recommend(client, plan, [source, liked, disliked], method=method)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["approval_required"] and not body["infeasibility_proven"]
    assert body["recommendations"][0]["food_id"] == liked["id"]
    assert len(body["recommendations"]) == 2
    result = body["recommendations"][0]
    assert result["check"]["valid"]
    assert Decimal(result["nutrient_delta"]["energy"]) == 0
    assert result["nutrient_delta"]["free_sugars"] is None
    parent = client.get(f"/api/plans/{plan['id']}").json()
    assert not parent["needs_review"]
    draft = client.post(
        f"/api/plans/{plan['id']}/substitutions", json={**CLINICIAN, **result["substitution"]}
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["approved_at"] is None
    assert approve_plan(client, draft.json()).status_code == 200
    assert recommend(client, plan, [liked]).status_code == 409


def test_restrictions_missing_targets_and_whole_day_bounds_filter_candidates(client):
    _, _, plan = fixture(client, allergies=["milk"])
    unknown = food(client, "unknown", nutrients=composition())
    excess = food(
        client, "excess", nutrients=composition(sodium=10000), allergen_status={"milk": "absent"}
    )
    missing = food(
        client, "missing", nutrients=composition(sodium=None), allergen_status={"milk": "absent"}
    )
    result = recommend(client, plan, [unknown, excess, missing], method="nearest").json()
    assert result["recommendations"] == []
    assert len(result["excluded_foods"]) == 2
    assert len(result["rejected_portions"]) == 3
    assert all(
        any(v.get("nutrient") == "sodium" for v in r["violations"])
        for r in result["rejected_portions"]
    )


def test_missing_features_baselines_and_stale_catalogue(client):
    _, _, plan = fixture(client)
    missing = food(client, "missing", nutrients=composition(protein=None))
    # This plan has no protein target, so missing protein only blocks similarity scoring.
    nearest = recommend(client, plan, [missing], method="nearest").json()
    assert nearest["recommendations"] == []
    assert missing["id"] in nearest["model"]["excluded_food_ids"]
    category = recommend(client, plan, [missing], method="same_category").json()
    assert len(category["recommendations"]) == 1
    assert category["recommendations"][0]["nutrient_distance"] is None
    bad = recommend(client, plan, [missing], day=2)
    assert bad.status_code == 422
    parent_food = plan["body"]["meals"][0]
    revised = client.post(
        f"/api/foods/{parent_food['food_id']}/revisions",
        json={**REVIEWER, "expected_revision": 1, "body": parent_food["food"]},
    )
    assert revised.status_code == 201
    assert recommend(client, plan, [missing]).status_code == 409
