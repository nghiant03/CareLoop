from careloop.adapters.fndds import MAPPING, normalize


def test_fndds_basis_nulls_and_zero_portions():
    row = {column: 1.0 for column in MAPPING.values()}
    row.update(
        {
            "Food code": 11111000,
            "Main food description": "Test milk",
            "WWEIA Category description": "Test",
            "Energy (kcal)": 61,
            "Sodium (mg)": None,
        }
    )
    portions = [
        {
            "Food code": 11111000,
            "Seq num": 1,
            "Portion description": "Test cup",
            "Portion weight\n(g)": 244,
        },
        {
            "Food code": 11111000,
            "Seq num": 2,
            "Portion description": "Unspecified",
            "Portion weight\n(g)": 0,
        },
    ]
    records, counts = normalize([row], portions, {"nutrients": "a" * 64, "portions": "b" * 64}, 0)
    body = records[0][1]
    assert body.nutrients.energy == 61
    assert body.nutrients.sodium is None and body.nutrients.free_sugars is None
    assert body.nutrients.total_sugars == 1
    assert body.portions[0].grams == 244
    assert body.allergen_status == {} and body.vegetarian is None
    assert body.planning_portions == [] and body.meal_slots == []
    assert counts["omitted_nonpositive_missing_or_oversized_portions"] == 1
