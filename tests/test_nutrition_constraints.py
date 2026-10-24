import io
import json
import sys
import urllib.request
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_patients import CLINICIAN, REVIEWER, approve, patient, propose
from test_planning import PATIENT, approve_plan, food, request

from careloop.evidence.conflicts import analyse
from careloop.evidence.diet_rules import KDIGO, WHO, build_rules, main, resolve_matches
from careloop.evidence.models import Action
from careloop.foods.models import FoodBody
from careloop.nutrition import incompatible, target_value
from careloop.patients.engine import evaluate_rule
from careloop.planning.checker import check_plan
from careloop.planning.search import candidates, rank

FACTS = {"allergies": [], "vegetarian": False, "include_eggs": True, "include_dairy": True}


def action(kind, subject, amount, unit="g/day", **extra):
    return Action(
        kind=kind, subject=subject, amount=amount, unit=unit, advice="Test", **extra
    ).model_dump()


def fixture(nutrients, groups=None):
    body = {
        "name": "Fixture",
        "category": "Test",
        "basis": "g",
        "nutrients": nutrients,
        "food_groups": groups or {},
        "portions": [{"id": "p", "label": "100 g", "grams": 100}],
        "allergen_status": {},
        "vegetarian": True,
        "contains_egg": False,
        "contains_dairy": False,
    }
    return {
        "day": 1,
        "slot": "lunch",
        "item": 1,
        "food_id": "f",
        "food_revision": 1,
        "food": body,
        "portion_id": "p",
        "scale": 1,
        "quantity": "100",
        "unit": "g",
    }


def check(meals, *actions, days=1):
    items = [
        {"action": action("range", "energy", 1, "kcal/day", upper=2000)},
        *[{"action": a} for a in actions],
    ]
    return check_plan(meals, days, ["lunch"], FACTS, items)


def test_minimum_is_hard_daily_bound_and_historical_intake_remains_soft():
    meal = fixture({"energy": 100, "fibre": 24})
    minimum = action("minimum", "fibre", 25)
    assert not check([meal], minimum)["valid"]
    assert check([meal], action("intake", "fibre", 25))["valid"]
    meal["food"]["nutrients"]["fibre"] = 25
    assert check([meal], minimum)["valid"]
    second = deepcopy(meal)
    second["day"] = 2
    second["food"]["nutrients"]["fibre"] = 24
    meal["food"]["nutrients"]["fibre"] = 26
    result = check([meal, second], minimum, days=2)
    assert not result["valid"] and result["violations"][0]["day"] == 2


def test_energy_percentage_uses_actual_energy_with_strict_boundary_and_unknowns():
    meal = fixture({"energy": 400, "free_sugars": 10})
    strict = action("ceiling", "free_sugars", 10, "%energy", upper_exclusive=True)
    assert not check([meal], strict)["valid"]  # 10g * 4 / 400 = 10%
    assert check([meal], {**strict, "upper_exclusive": False})["valid"]
    meal["food"]["nutrients"]["energy"] = 800
    assert check([meal], strict)["valid"]
    for value in (0, None):
        meal["food"]["nutrients"]["energy"] = value
        assert not check([meal], strict)["valid"]
    assert target_value(
        action("ceiling", "saturated_fat", 10, "%energy"), {"energy": 900, "saturated_fat": 10}
    ) == Decimal(10)


def test_food_group_contributions_unknown_is_not_zero_and_requires_review():
    meal = fixture({"energy": 100}, {"fruit_and_vegetables": 50})
    minimum = action("minimum", "fruit_and_vegetables", 50)
    assert check([meal], minimum)["valid"]
    meal["food"]["food_groups"] = {}
    assert not check([meal], minimum)["valid"]
    options, excluded = candidates(
        [{"id": "f", "latest_revision": 1, "body": meal["food"]}],
        ["lunch"],
        FACTS,
        [{"action": minimum}],
    )
    assert not options["lunch"] and "fruit_and_vegetables" in str(excluded)
    body = {
        **meal["food"],
        "food_groups": {"fruit_and_vegetables": 100},
        "provenance": {"kind": "manual", "source": "test", "notes": "Test"},
    }
    with pytest.raises(ValidationError, match="review note"):
        FoodBody.model_validate(body)
    body["review_note"] = "Documented edible contribution"
    FoodBody.model_validate(body)
    body["food_groups"]["fruit_and_vegetables"] = 101
    with pytest.raises(ValidationError, match="cannot exceed"):
        FoodBody.model_validate(body)


def test_action_validation_conflicts_and_search_units():
    for subject in ("energy", "sodium", "fibre", "fruit_and_vegetables"):
        with pytest.raises(ValidationError, match="Unsupported energy-percentage"):
            action("ceiling", subject, 10, "%energy")
    with pytest.raises(ValidationError):
        action("minimum", "fibre", 25, upper_exclusive=True)
    with pytest.raises(ValidationError):
        action("ceiling", "fat", 101, "%energy")
    minimum = action("minimum", "fibre", 25)
    ceiling = action("ceiling", "fibre", 25, upper_exclusive=True)
    assert incompatible(minimum, ceiling)
    assert not incompatible(minimum, {**ceiling, "upper_exclusive": False})
    rows = [
        {
            "rule_id": str(i),
            "revision": 1,
            "body": {
                "action": a,
                "applicability": [],
                "exceptions": [],
                "source_id": "source",
                "location": "section",
                "quote": "quote",
            },
        }
        for i, a in enumerate([minimum, ceiling])
    ]
    assert len(analyse(rows, {"0"})["blocking_conflicts"]) == 1
    good = fixture({"energy": 400, "free_sugars": 5, "fibre": 25})
    bad = fixture({"energy": 400, "free_sugars": 20, "fibre": 0})
    percentage = action("ceiling", "free_sugars", 10, "%energy")
    assert rank([good], [percentage, minimum], 1, FACTS, set(), "nutrient_fit") < rank(
        [bad], [percentage, minimum], 1, FACTS, set(), "nutrient_fit"
    )
    # Percentages aren't multiplied by how many meal positions have been filled.
    assert rank([good], [percentage], 0.25, FACTS, set(), "nutrient_fit") == 0


def test_evidence_percent_and_per_kg_minimum_are_executable():
    body = {
        "action": action("minimum", "protein", 0.8, "g/kg/day"),
        "applicability": [],
        "exceptions": [],
        "source_id": "source",
        "quote": "quote",
        "location": "location",
        "population_note": "Test",
        "exception_note": "Test",
    }
    rule = {"rule_id": "r", "revision": 1, "body": body}
    assert evaluate_rule(rule, {})["status"] == "incomplete"
    result = evaluate_rule(rule, {"weight_kg": 70})
    assert result["action"]["amount"] == 56 and result["action"]["unit"] == "g/day"
    body["action"] = action("ceiling", "saturated_fat", 10, "%energy")
    assert evaluate_rule(rule, {})["status"] == "applicable"


def sample_sources():
    who = {
        "id": "00000000-0000-0000-0000-000000000001",
        "content": "\n\n".join(
            [
                "Carbohydrates\nEveryone older than 10 years of age should aim for at least "
                "400 grams of fruits and vegetables per day.",
                "Carbohydrates\nEveryone older than 10 years of age should also aim for a daily "
                "intake of at least 25 grams of naturally-occurring dietary fibre; at least "
                "15 or 21 grams for children 2–5 or 6–9 years of age.",
                "Sugars\nThe consumption of free sugars should be limited to less than 10% "
                "of total daily energy intake.",
                "Fats\nNo more than 10% of total energy intake should come from saturated fat "
                "and no more than 1% of total energy from trans fat.",
                "Sodium\nIn adults, salt intake should be limited to less than 5 grams per day "
                "(2 grams per day sodium).",
            ]
        ),
    }
    kdigo = {
        "id": "00000000-0000-0000-0000-000000000002",
        "content": "3.3.2 Sodium intake\nRecommendation 3.3.2.1: We suggest that sodium intake "
        "be <2 g of sodium per day in people with CKD (2C).\n\n"
        "Practice Point 3.3.2.1: Dietary sodium restriction is usually not appropriate "
        "for patients with sodium-wasting nephropathy.",
    }
    return who, kdigo


def test_source_backed_baseline_and_ckd_scopes():
    who, kdigo = sample_sources()
    plans = build_rules(who, kdigo)
    assert len(plans) == 9
    adult = {"age_years": 35, "conditions": [], "has_ckd": False}
    statuses = {}
    for entry in plans:
        rule = {"rule_id": entry["key"], "revision": 1, "body": entry["body"]}
        statuses[entry["key"]] = evaluate_rule(rule, adult)["status"]
        assert (
            entry["body"]["quote"] in (kdigo if entry["key"].startswith("ckd") else who)["content"]
        )
        if entry["key"] == "ckd-adult-sodium":
            assert evaluate_rule(rule, {**adult, "has_ckd": True})["status"] == "applicable"
            assert (
                evaluate_rule(
                    rule, {**adult, "has_ckd": True, "conditions": ["sodium-wasting nephropathy"]}
                )["status"]
                == "excluded"
            )
            assert evaluate_rule(rule, {"age_years": 35})["status"] == "incomplete"
    assert sum(s == "applicable" for s in statuses.values()) == 6
    with pytest.raises(ValueError, match="Source recommendation changed"):
        build_rules(
            {**who, "content": who["content"].replace("at least 400 grams", "at least 500 grams")},
            kdigo,
        )


def test_rule_matching_prefers_published_and_rejects_real_ambiguity():
    plan = build_rules(*sample_sources())
    entry = plan[6]
    draft = {
        "id": "draft",
        "retired": False,
        "active_revision": None,
        "draft": {**entry["body"], "blockers": ["Review extraction"]},
    }
    published = {**draft, "id": "published", "active_revision": 2}
    assert resolve_matches([entry], [draft, published]) == [(entry, published)]
    with pytest.raises(RuntimeError, match="Ambiguous existing rules"):
        resolve_matches(plan, [published, {**published, "id": "other"}])
    with pytest.raises(RuntimeError, match="Ambiguous existing rules"):
        resolve_matches(plan, [draft, {**draft, "id": "other"}])


def test_rule_publication_command_revises_and_is_idempotent(client, monkeypatch, tmp_path):
    saved = []
    for url, source in zip((WHO, KDIGO), sample_sources(), strict=True):
        response = client.post(
            "/api/evidence/sources",
            json={
                **REVIEWER,
                "title": "Test source",
                "edition": "Test",
                "locator": url,
                "content": source["content"],
            },
        )
        assert response.status_code == 201, response.text
        saved.append(response.json())
    old = build_rules(*saved)[1]["body"]
    old["action"] = {"kind": "assessment", "subject": "fibre", "advice": "Previous guidance"}
    response = client.post("/api/evidence/rules", json={**REVIEWER, "body": old})
    assert response.status_code == 201
    original_id = response.json()["id"]

    interrupt = True

    def urlopen(request, timeout=0):
        url = request if isinstance(request, str) else request.full_url
        path = url.removeprefix("http://testserver")
        if interrupt and path == "/api/evidence/approvals":
            raise RuntimeError("Simulated interruption after draft writes")
        response = (
            client.get(path)
            if isinstance(request, str) or request.data is None
            else client.post(path, json=json.loads(request.data))
        )
        assert response.status_code < 300, response.text
        return io.BytesIO(response.content)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        ["diet_rules", "--api", "http://testserver/api", "--output", str(tmp_path), "--apply"],
    )
    with pytest.raises(RuntimeError, match="Simulated interruption"):
        main()
    interrupted = client.get("/api/evidence/catalogue").json()
    interrupt = False
    main()
    catalogue = client.get("/api/evidence/catalogue").json()
    assert len(catalogue["rules"]) == 9
    assert all(r["active_revision"] is not None for r in catalogue["rules"])
    revised = next(r for r in catalogue["rules"] if r["id"] == original_id)
    assert revised["latest_revision"] == 2 and revised["published"]["action"]["kind"] == "minimum"
    assert {r["id"]: r["latest_revision"] for r in interrupted["rules"]} == {
        r["id"]: r["latest_revision"] for r in catalogue["rules"]
    }
    blocked = deepcopy(build_rules(*saved)[6]["body"])
    blocked["blockers"] = ["Review extracted applicability"]
    response = client.post("/api/evidence/rules", json={**REVIEWER, "body": blocked})
    assert response.status_code == 201
    catalogue = client.get("/api/evidence/catalogue").json()
    main()
    assert client.get("/api/evidence/catalogue").json() == catalogue


def test_api_search_approval_substitution_and_logging_enforce_new_targets(client):
    p = patient(client, **FACTS)
    target = propose(client, p)
    actions = [
        action("range", "energy", 900, "kcal/day", upper=1200),
        action("minimum", "fibre", 25),
        action("ceiling", "saturated_fat", 10, "%energy", upper_exclusive=True),
    ]
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "dispositions": [],
            "manual": [{"action": a, "rationale": "Test"} for a in actions],
        },
    )
    assert response.status_code == 201, response.text
    target = response.json()
    assert approve(client, target).status_code == 200
    good = food(client, nutrients={"energy": 350, "fibre": 10, "saturated_fat": 1})
    bad = food(client, "bad", nutrients={"energy": 350, "fibre": 0, "saturated_fat": 20})
    unknown = food(client, "unknown", nutrients={"energy": 350, "fibre": 10})
    result = request(client, target, [good, bad, unknown])
    assert result["outcome"]["status"] == "drafts_available"
    assert any(row["food_id"] == unknown["id"] for row in result["outcome"]["excluded_foods"])
    plan = next(p for p in result["alternatives"] if p["body"]["check"]["valid"])
    assert all(m["food_id"] == good["id"] for m in plan["body"]["meals"])
    assert approve_plan(client, plan).status_code == 200
    replaced = client.post(
        f"/api/plans/{plan['id']}/substitutions",
        json={
            **PATIENT,
            "day": 1,
            "slot": "lunch",
            "food_id": bad["id"],
            "portion_id": "serving",
            "scale": 1,
        },
    )
    assert replaced.status_code == 201, replaced.text
    assert not replaced.json()["body"]["check"]["valid"]
    assert approve_plan(client, replaced.json()).status_code == 409
    base = f"/api/patients/{p['id']}"
    response = client.post(
        base + "/meal-logs",
        json={
            **PATIENT,
            "logged_on": "2026-11-01",
            "slot": "lunch",
            "status": "independent",
            "food_id": bad["id"],
            "portion_id": "serving",
            "scale": 1,
        },
    )
    assert response.status_code == 201
    day = base + "/meal-log-days/2026-11-01"
    params = {"target_id": target["id"]}
    partial = client.get(day + "/target-comparison", params=params).json()["comparisons"]
    assert partial[1]["status"] == "partial_below_minimum"
    assert partial[2]["status"] == "partial_day"
    assert client.post(day, json={**PATIENT, "complete": True}).status_code == 200
    complete = client.get(day + "/target-comparison", params=params).json()["comparisons"]
    assert complete[1]["status"] == "below_minimum"
    assert complete[2]["status"] == "above_ceiling"
    assert Decimal(complete[2]["recorded"]) > 50
