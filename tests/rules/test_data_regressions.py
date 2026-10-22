import json

import pytest

from backend.datasets import usda_fill_gaps as usda
from backend.datasets.paths import dataset_path
from backend.datasets.patient import Patient
from backend.datasets.patients_generator import ARCHETYPES, generate


def dish(**overrides):
    return {"dish_id": "TEST", "portion_g": 100, "ingredients": ["fish"],
            "potassium_mg": None, "phosphorus_mg": None, "verified": True,
            "provenance": "hpb_import", "tags": ["lean_protein"], **overrides}


def foods(_url, **_kwargs):
    return {"foods": [{"description": "fish", "fdcId": 1,
                       "foodNutrients": [{"nutrientId": 1092, "value": 800},
                                         {"nutrientId": 1091, "value": 400}]}]}


def test_estimated_values_clear_verification_and_update_only_nutrient_roles(monkeypatch):
    monkeypatch.setattr(usda, "_http_get_json", foods)
    source = dish()
    output = usda.estimate_dish_gaps(source)
    assert output["verified"] is False
    assert output["provenance"] == "usda_estimate"
    assert set(output["tags"]) == {"lean_protein", "high_potassium", "high_phosphorus"}
    assert source == dish()
    unchanged = dish(potassium_mg=400, phosphorus_mg=200)
    assert usda.estimate_dish_gaps(unchanged)["verified"] is True


def test_rate_limit_discards_partial_dish_and_stops_file_import(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(usda, "_http_get_json", foods)
    path = tmp_path / "dishes.json"
    originals = [dish(dish_id="COMPLETE"), dish(dish_id="PARTIAL", ingredients=["fish", "rice"]),
                 dish(dish_id="UNTOUCHED")]
    path.write_text(json.dumps(originals))
    budget = usda.RequestBudget(max_requests=2)
    result, count = usda.fill_gaps_in_file(path, budget=budget)
    assert count == 1
    assert result[0]["verified"] is False
    assert result[1:] == originals[1:]
    assert budget.used == 2
    assert "stopping" in capsys.readouterr().err


def test_local_exhaustion_has_actionable_recovery():
    budget = usda.RequestBudget(max_requests=0)
    with pytest.raises(usda.RateLimitError, match="waiting or changing keys does not reset"):
        budget.take()


def test_remote_rate_limit_propagates_and_cli_probe_fails(monkeypatch, capsys):
    def limited(*_args, **_kwargs):
        raise usda.RateLimitError("HTTP 429")
    monkeypatch.setattr(usda, "_http_get_json", limited)
    with pytest.raises(usda.RateLimitError, match="429"):
        usda.estimate_kp_for_ingredient("rice", 100)
    assert usda.main(["--ingredient", "rice"]) == 1
    assert "429" in capsys.readouterr().err


def test_file_cli_reports_actual_budget_and_preserves_tuple_contract(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(usda, "_http_get_json", foods)
    path = tmp_path / "dishes.json"
    out = tmp_path / "filled.json"
    path.write_text(json.dumps([dish()]))
    assert usda.main(["--dishes", str(path), "--out", str(out)]) == 0
    assert "requests used: 1/30" in capsys.readouterr().out
    assert json.loads(out.read_text())[0]["verified"] is False


def test_stage_five_generator_and_existing_fixtures_are_excluded():
    assert ARCHETYPES["CKD5_pre_dialysis_hyperPO4"]["exclude"] is True
    records = generate(n=9, seed=0)
    generated = [p for p in records if p.archetype == "CKD5_pre_dialysis_hyperPO4"]
    assert generated and all(p.exclude_from_careloop for p in generated)
    fixtures = json.loads(dataset_path("patients.json").read_text())
    assert all(p["exclude_from_careloop"] for p in fixtures
               if "CKD_stage_5_pre_dialysis" in p["diagnoses"])
    record = Patient.model_validate(fixtures[0])
    summary = record.to_summary()
    assert summary.snapshot_version == 2
    assert summary.bmi == record.bmi
    assert summary.hba1c_pct == record.hba1c_pct


def test_curated_tags_are_recipe_roles_not_fat_thresholds():
    dishes = {d["dish_id"]: d for d in json.loads(dataset_path("dishes.json").read_text())}
    for record in dishes.values():
        assert len(record["tags"]) == len(set(record["tags"]))
        if record["category"] in {"drink", "dessert"}:
            assert "lean_protein" not in record["tags"]
    for dish_id in ["SG0045", "SG0141", "SG0148"]:
        assert "lean_protein" not in dishes[dish_id]["tags"]
    for dish_id in ["SG0005", "SG0011", "SG0153", "SG0214"]:
        assert "deep_fried" not in dishes[dish_id]["tags"]
    for dish_id in ["SG0084", "SG0102", "SG0104", "SG0113", "SG0120", "SG0154"]:
        assert "deep_fried" in dishes[dish_id]["tags"]
    assert dishes["SG0102"]["fat_g"] <= 20
    assert dishes["SG0214"]["fat_g"] > 20
    assert "lean_protein" in dishes["SG0214"]["tags"]
