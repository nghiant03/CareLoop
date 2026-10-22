from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_list_dishes_returns_full_catalogue() -> None:
    r = client.get("/dishes")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 214
    assert len(body["dishes"]) == body["count"]
    first = body["dishes"][0]
    for field in ("dish_id", "name", "category", "energy_kcal", "sodium_mg"):
        assert field in first


def test_list_dishes_category_filter() -> None:
    all_dishes = client.get("/dishes").json()["dishes"]
    categories = {d["category"] for d in all_dishes}
    some_category = min(categories)
    r = client.get("/dishes", params={"category": some_category})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all(d["category"] == some_category for d in body["dishes"])
    assert body["count"] == sum(
        1 for d in all_dishes if d["category"] == some_category
    )


def test_list_dishes_search_filter_case_insensitive() -> None:
    r = client.get("/dishes", params={"search": "CHICKEN"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all("chicken" in d["name"].lower() for d in body["dishes"])


def test_get_dish_detail() -> None:
    some_id = client.get("/dishes").json()["dishes"][0]["dish_id"]
    r = client.get(f"/dishes/{some_id}")
    assert r.status_code == 200
    dish = r.json()
    assert dish["dish_id"] == some_id
    assert "ingredients" in dish
    for field in (
        "energy_kcal",
        "protein_g",
        "sodium_mg",
        "potassium_mg",
        "phosphorus_mg",
        "carbs_g",
    ):
        assert field in dish


def test_get_dish_unknown_404() -> None:
    r = client.get("/dishes/DOES-NOT-EXIST")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "dish_not_found"
