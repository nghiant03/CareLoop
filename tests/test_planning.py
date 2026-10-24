from copy import deepcopy

from test_patients import CLINICIAN, REVIEWER, approve, patient, propose, rule

from careloop.planning.checker import check_plan

PATIENT = {"actor": {"name": "Test patient", "role": "patient"}, "reason": "Test request"}


def food(client, code="one", *, energy=330, sodium=100, name="Reviewed test dish", **overrides):
    body = {
        "name": name,
        "category": "Test-only meal",
        "nutrients": {"energy": energy, "protein": 10, "sodium": sodium},
        "portions": [{"id": "serving", "label": "test serving", "grams": 100}],
        "provenance": {"kind": "manual", "source": "test://fixture", "notes": "Not clinical data"},
        "review_note": "Test-only planning annotations",
        **overrides,
    }
    response = client.post(
        "/api/foods", json={**REVIEWER, "namespace": "test", "external_id": code, "body": body}
    )
    assert response.status_code == 201, response.text
    return response.json()


def ready(client, **facts):
    p = patient(
        client,
        **{
            "allergies": [],
            "vegetarian": False,
            "include_eggs": True,
            "include_dairy": True,
            **facts,
        },
    )
    target = propose(client, p)
    edited = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "dispositions": [],
            "manual": [
                {
                    "action": {
                        "kind": "range",
                        "subject": "energy",
                        "amount": 900,
                        "upper": 1200,
                        "unit": "kcal/day",
                        "advice": "Test only",
                    },
                    "rationale": "Test range",
                },
                {
                    "action": {
                        "kind": "ceiling",
                        "subject": "sodium",
                        "amount": 2000,
                        "unit": "mg/day",
                        "advice": "Test only",
                    },
                    "rationale": "Test ceiling",
                },
            ],
        },
    )
    assert edited.status_code == 201, edited.text
    assert approve(client, edited.json()).status_code == 200
    return p, edited.json()


def request(client, target, foods, **options):
    response = client.post(
        "/api/plan-requests",
        json={
            **PATIENT,
            "target_id": target["id"],
            "target_revision": target["latest_revision"],
            "start_date": "2026-11-01",
            "days": 1,
            "food_ids": [f["id"] for f in foods],
            **options,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve_plan(client, plan):
    return client.post(
        f"/api/plans/{plan['id']}/approval", json={**CLINICIAN, "review_note": "Test review"}
    )


def test_patient_requests_and_clinician_approvals_have_separate_roles(client):
    _, target = ready(client)
    f = food(client)
    for actor in (CLINICIAN, REVIEWER):
        assert (
            client.post(
                "/api/plan-requests",
                json={
                    **actor,
                    "target_id": target["id"],
                    "target_revision": target["latest_revision"],
                    "start_date": "2026-11-01",
                    "days": 1,
                    "food_ids": [f["id"]],
                },
            ).status_code
            == 403
        )
    plan = request(client, target, [f])["alternatives"][0]
    assert (
        client.post(
            f"/api/plans/{plan['id']}/approval",
            json={
                **PATIENT,
                "review_note": "Cannot self-approve",
            },
        ).status_code
        == 403
    )
    assert approve_plan(client, plan).status_code == 200
    assert (
        client.post(
            f"/api/plans/{plan['id']}/substitutions",
            json={
                **CLINICIAN,
                "day": 1,
                "slot": "lunch",
                "food_id": f["id"],
                "portion_id": "serving",
            },
        ).status_code
        == 403
    )


def test_three_checked_alternatives_seven_days_and_selection(client):
    p, target = ready(client, dislikes=["Disliked"])
    foods = [
        food(client, "one", name="Disliked dish"),
        food(client, "two", energy=350),
        food(client, "three", energy=370),
    ]
    result = request(
        client, target, foods, days=7, schedule=["breakfast", "lunch", "dinner", "snack"]
    )
    assert result["outcome"]["status"] == "drafts_available"
    assert {p["objective"] for p in result["alternatives"]} == {
        "nutrient_fit",
        "preference_match",
        "variety",
    }
    for plan in result["alternatives"]:
        assert len(plan["body"]["meals"]) == 28
        check = check_plan(
            plan["body"]["meals"],
            7,
            ["breakfast", "lunch", "dinner", "snack"],
            p["body"]["facts"],
            target["body"]["items"],
        )
        assert check["valid"]
        assert check == plan["body"]["check"]
        assert check["daily_totals"]["1"]["free_sugars"] is None
    assert approve_plan(client, result["alternatives"][1]).status_code == 200
    assert approve_plan(client, result["alternatives"][0]).status_code == 409


def test_allergy_and_vegetarian_checks_remain_after_preference_removal(client):
    _, target = ready(
        client, allergies=["egg"], vegetarian=True, include_eggs=False, include_dairy=False
    )
    unknown = food(client)
    result = request(client, target, [unknown])
    assert result["outcome"]["status"] == "blocked"
    assert result["alternatives"] == []
    reasons = result["outcome"]["excluded_foods"][0]["reasons"]
    assert "egg: unknown" in reasons
    assert len(reasons) == 2
    safe = food(
        client,
        "reviewed",
        allergen_status={"egg": "absent"},
        vegetarian=True,
        contains_egg=False,
        contains_dairy=False,
    )
    result = request(client, target, [safe])
    assert all(p["body"]["check"]["valid"] for p in result["alternatives"])


def test_legacy_egg_dairy_preferences_do_not_block_generation_or_approval(client):
    for value in (None, False):
        _, target = ready(client, include_eggs=value, include_dairy=value)
        candidate = food(client, f"legacy-{value}", contains_egg=None, contains_dairy=None)
        result = request(client, target, [candidate])
        assert result["outcome"]["status"] == "drafts_available"
        assert approve_plan(client, result["alternatives"][0]).status_code == 200


def test_missing_patient_choices_block_but_source_portions_need_no_enablement(client):
    _, target = ready(client, allergies=None)
    f = food(client)
    assert request(client, target, [f])["outcome"]["status"] == "blocked"
    _, target = ready(client)
    raw = food(client, "raw", meal_slots=[], planning_portions=[], review_note=None)
    result = request(client, target, [raw])
    assert all(plan["body"]["check"]["valid"] for plan in result["alternatives"])
    assert len(result["alternatives"]) == 3
    assert "meal_slots" not in raw["body"] and "planning_portions" not in raw["body"]
    no_quantity = food(client, "no-quantity", portions=[], review_note=None)
    result = request(client, target, [no_quantity])
    assert result["alternatives"] == []
    assert "No source portion" in result["outcome"]["excluded_foods"][0]["reasons"][0]


def test_unmet_search_is_not_infeasibility_and_cannot_be_approved(client):
    _, target = ready(client)
    f = food(client, energy=1)
    result = request(client, target, [f])
    assert result["outcome"]["status"] == "search_failed"
    assert result["outcome"]["infeasibility_proven"] is False
    assert len(result["alternatives"]) == 3
    for plan in result["alternatives"]:
        assert not plan["body"]["check"]["valid"]
        assert approve_plan(client, plan).status_code == 409


def test_independent_checker_recomputes_grams_totals_coverage_and_restrictions(client):
    p, target = ready(client)
    f = food(client)
    plan = request(client, target, [f])["alternatives"][0]
    meals = deepcopy(plan["body"]["meals"])
    meals[0]["quantity"] = "999"
    check = check_plan(
        meals, 1, ["breakfast", "lunch", "dinner"], p["body"]["facts"], target["body"]["items"]
    )
    assert not check["valid"]
    assert any(v["issue"] == "Portion quantity/unit mismatch" for v in check["violations"])
    meals = deepcopy(plan["body"]["meals"])
    meals[0]["food"]["nutrients"]["sodium"] = None
    assert (
        check_plan(
            meals, 1, ["breakfast", "lunch", "dinner"], p["body"]["facts"], target["body"]["items"]
        )["daily_totals"]["1"]["sodium"]
        is None
    )
    assert not check_plan(
        meals[:-1], 1, ["breakfast", "lunch", "dinner"], p["body"]["facts"], target["body"]["items"]
    )["valid"]


def test_food_revision_flags_plans_without_rewriting_history(client):
    _, target = ready(client)
    f = food(client)
    plan = request(client, target, [f])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    body = deepcopy(f["body"])
    body["nutrients"]["sodium"] = 999
    response = client.post(
        f"/api/foods/{f['id']}/revisions", json={**REVIEWER, "expected_revision": 1, "body": body}
    )
    assert response.status_code == 201
    historical = client.get(f"/api/plans/{plan['id']}").json()
    assert historical["needs_review"] and historical["approved_at"]
    assert historical["body"]["meals"][0]["food"]["nutrients"]["sodium"] == 100
    assert len(client.get(f"/api/foods/{f['id']}").json()["revisions"]) == 2
    assert (
        client.post(
            f"/api/foods/{f['id']}/revisions",
            json={**REVIEWER, "expected_revision": 1, "body": body},
        ).status_code
        == 409
    )


def test_new_allergen_flags_affected_meals_and_blocks_new_requests(client):
    p, target = ready(client)
    f = food(client, allergen_status={"egg": "present"})
    plan = request(client, target, [f])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    body = deepcopy(p["body"])
    body["facts"]["allergies"] = ["egg"]
    client.post(
        f"/api/patients/{p['id']}/revisions",
        json={**CLINICIAN, "expected_revision": 1, "body": body},
    )
    historical = client.get(f"/api/plans/{plan['id']}").json()
    assert historical["needs_review"]
    assert len(historical["allergy_alerts"]) == 3
    response = client.post(
        "/api/plan-requests",
        json={
            **PATIENT,
            "target_id": target["id"],
            "target_revision": 2,
            "start_date": "2026-11-01",
            "days": 1,
            "food_ids": [f["id"]],
        },
    )
    assert response.status_code == 409
    assert (
        client.post(
            f"/api/plans/{plan['id']}/substitutions",
            json={
                **PATIENT,
                "day": 1,
                "slot": "lunch",
                "food_id": f["id"],
                "portion_id": "serving",
            },
        ).status_code
        == 409
    )


def test_substitution_draft_is_checked_and_does_not_mutate_parent(client):
    _, target = ready(client)
    f = food(client)
    replacement = food(client, "replacement")
    salty = food(client, "salty", sodium=10000)
    parent = request(client, target, [f])["alternatives"][0]
    assert approve_plan(client, parent).status_code == 200
    original = client.get(f"/api/plans/{parent['id']}").json()["body"]
    bad = client.post(
        f"/api/plans/{parent['id']}/substitutions",
        json={
            **PATIENT,
            "day": 1,
            "slot": "lunch",
            "food_id": salty["id"],
            "portion_id": "serving",
        },
    )
    assert bad.status_code == 201 and not bad.json()["body"]["check"]["valid"]
    assert approve_plan(client, bad.json()).status_code == 409
    draft = client.post(
        f"/api/plans/{parent['id']}/substitutions",
        json={
            **PATIENT,
            "day": 1,
            "slot": "lunch",
            "food_id": replacement["id"],
            "portion_id": "serving",
            "scale": original["meals"][1]["scale"],
        },
    )
    assert draft.status_code == 201
    assert client.get(f"/api/plans/{parent['id']}").json()["body"] == original
    assert not client.get(f"/api/plans/{parent['id']}").json()["needs_review"]
    assert approve_plan(client, draft.json()).status_code == 200
    assert client.get(f"/api/plans/{parent['id']}").json()["needs_review"]


def test_published_evidence_and_new_targets_propagate_plan_flags(client):
    p, target = ready(client)
    f = food(client)
    plan = request(client, target, [f])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    rule(client)
    assert client.get(f"/api/plans/{plan['id']}").json()["needs_review"]
    assert client.get(f"/api/plans/{plan['id']}").json()["review_reasons"] == ["evidence_changed"]
