from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from test_patients import CLINICIAN, REVIEWER, patient
from test_planning import approve_plan, food, ready, request

PATIENT = {"actor": {"name": "Demo patient", "role": "patient"}, "reason": "Recorded intake"}


def setup_plan(client):
    p, target = ready(client)
    f = food(client)
    plan = request(client, target, [f])["alternatives"][0]
    assert approve_plan(client, plan).status_code == 200
    return p, f, plan


def planned(plan, **changes):
    return {
        **PATIENT,
        "logged_on": "2026-11-01",
        "slot": "breakfast",
        "plan_id": plan["id"],
        "status": "as_planned",
        **changes,
    }


def test_confirm_correct_history_and_day_completeness(client):
    p, _, plan = setup_plan(client)
    base = f"/api/patients/{p['id']}"
    day = base + "/meal-log-days/2026-11-01"
    empty = client.get(day).json()
    assert not empty["complete"] and empty["recorded_totals"]["energy"] is None
    data = planned(plan)
    response = client.post(base + "/meal-logs", json=data)
    assert response.status_code == 201, response.text
    entry = response.json()
    meal = plan["body"]["meals"][0]
    expected = Decimal(meal["quantity"]) * Decimal("3.3")
    assert Decimal(entry["body"]["nutrients"]["energy"]) == expected
    assert client.post(base + "/meal-logs", json=data).status_code == 409
    assert client.post(day, json={**PATIENT, "complete": True}).json()["complete"]
    correction = {**data, "status": "changed_quantity", "scale": 2.25, "expected_revision": 1}
    path = base + f"/meal-logs/{entry['id']}"
    updated = client.post(path + "/revisions", json=correction)
    assert updated.status_code == 201, updated.text
    assert Decimal(updated.json()["body"]["nutrients"]["energy"]) == Decimal("742.5")
    assert client.post(path + "/revisions", json=correction).status_code == 409
    assert len(client.get(path).json()["history"]) == 2
    summary = client.get(day).json()
    assert not summary["complete"]
    slots = client.get(base + "/meal-log-days/2026-11-01", params={"plan_id": plan["id"]}).json()[
        "planned_slots"
    ]
    assert {s["slot"]: s["status"] for s in slots} == {
        "breakfast": "changed_quantity",
        "lunch": "unlogged",
        "dinner": "unlogged",
    }
    assert Decimal(summary["recorded_totals"]["energy"]) == Decimal("742.5")
    assert summary["recorded_totals"]["free_sugars"] is None


def test_skipped_replaced_and_independent_volume(client):
    p, _, plan = setup_plan(client)
    base = f"/api/patients/{p['id']}"
    skip = client.post(base + "/meal-logs", json=planned(plan, status="skipped"))
    assert skip.status_code == 201
    assert skip.json()["body"]["consumed"] is None
    assert set(skip.json()["body"]["nutrients"].values()) == {"0"}
    drink = food(
        client,
        "drink",
        energy=20,
        basis="ml",
        portions=[{"id": "cup", "label": "cup", "millilitres": 250}],
        planning_portions=[],
        meal_slots=[],
    )
    replacement = planned(
        plan, status="replaced", slot="lunch", food_id=drink["id"], portion_id="cup", scale=0.75
    )
    result = client.post(base + "/meal-logs", json=replacement)
    assert result.status_code == 201, result.text
    assert Decimal(result.json()["body"]["nutrients"]["energy"]) == Decimal("37.5")
    independent = {**replacement, "status": "independent", "plan_id": None, "slot": "snack"}
    assert client.post(base + "/meal-logs", json=independent).status_code == 201
    summary = client.get(base + "/meal-log-days/2026-11-01").json()
    assert len(summary["entries"]) == 3
    assert Decimal(summary["recorded_totals"]["energy"]) == 75
    assert not summary["complete"]


def test_plan_ownership_approval_date_roles_and_input_validation(client):
    p, target = ready(client)
    plan = request(client, target, [food(client)])["alternatives"][0]
    base = f"/api/patients/{p['id']}/meal-logs"
    assert client.post(base, json=planned(plan)).status_code == 409
    assert approve_plan(client, plan).status_code == 200
    other = patient(client)
    assert (
        client.post(f"/api/patients/{other['id']}/meal-logs", json=planned(plan)).status_code == 422
    )
    assert client.post(base, json=planned(plan, logged_on="2026-11-02")).status_code == 422
    assert client.post(base, json={**planned(plan), **REVIEWER}).status_code == 403
    assert client.post(base, json=planned(plan, status="changed_quantity")).status_code == 422
    assert client.post(base, json=planned(plan, scale=1)).status_code == 422
    assert (
        client.post(base, json=planned(plan, status="changed_quantity", scale=0)).status_code == 422
    )


def test_concurrent_confirmation_records_once(client):
    p, _, plan = setup_plan(client)
    path = f"/api/patients/{p['id']}/meal-logs"
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(lambda _: client.post(path, json=planned(plan)).status_code, range(2))
        )
    assert sorted(statuses) == [201, 409]
    summary = client.get(f"/api/patients/{p['id']}/meal-log-days/2026-11-01").json()
    assert len(summary["entries"]) == 1


def test_target_comparison_distinguishes_partial_complete_unknown_and_stale(client):
    p, f, plan = setup_plan(client)
    base = f"/api/patients/{p['id']}"
    day = base + "/meal-log-days/2026-11-01"
    comparison = day + "/target-comparison"
    query = {"target_id": plan["target_id"]}
    empty = client.get(comparison, params=query).json()
    assert all(item["status"] == "unknown_intake" for item in empty["comparisons"])
    result = client.post(
        base + "/meal-logs",
        json={
            **PATIENT,
            "logged_on": "2026-11-01",
            "slot": "breakfast",
            "status": "independent",
            "food_id": f["id"],
            "portion_id": "serving",
            "scale": 1,
        },
    )
    assert result.status_code == 201
    partial = client.get(comparison, params=query).json()
    assert [item["status"] for item in partial["comparisons"]] == [
        "partial_day",
        "partial_within_ceiling",
    ]
    client.post(day, json={**PATIENT, "complete": True})
    complete = client.get(comparison, params=query).json()
    assert [item["status"] for item in complete["comparisons"]] == ["below_range", "within_ceiling"]
    edited = client.post(
        base + "/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "body": {**p["body"], "facts": {**p["body"]["facts"], "weight_kg": 70}},
        },
    )
    assert edited.status_code == 201, edited.text
    stale = client.get(comparison, params=query).json()
    assert stale["target_needs_review"]
    assert stale["comparisons"] == complete["comparisons"]


def test_historical_plan_and_food_snapshots_remain_loggable(client):
    p, f, plan = setup_plan(client)
    body = {**f["body"], "nutrients": {**f["body"]["nutrients"], "energy": 999}}
    revised = client.post(
        f"/api/foods/{f['id']}/revisions", json={**REVIEWER, "expected_revision": 1, "body": body}
    )
    assert revised.status_code == 201, revised.text
    assert client.get(f"/api/plans/{plan['id']}").json()["needs_review"]
    logged = client.post(f"/api/patients/{p['id']}/meal-logs", json=planned(plan))
    assert logged.status_code == 201, logged.text
    assert logged.json()["body"]["consumed"]["food"]["nutrients"]["energy"] == 330
    assert logged.json()["body"]["consumed"]["food_revision"] == 1
    assert client.get(f"/api/plans/{plan['id']}").json()["needs_review"]
    entry = logged.json()
    invalid = {**planned(plan, slot="lunch"), **CLINICIAN, "expected_revision": 1}
    assert (
        client.post(
            f"/api/patients/{p['id']}/meal-logs/{entry['id']}/revisions", json=invalid
        ).status_code
        == 422
    )
