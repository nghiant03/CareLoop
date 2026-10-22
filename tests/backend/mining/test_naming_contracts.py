from backend.mining import comparison, substitutions


def test_verification_bonus_can_change_order_without_an_exact_tie(monkeypatch):
    query = {"dish_id": "query", "name": "Query", "category": "test"}
    nearer = {"dish_id": "nearer", "name": "Nearer", "category": "test"}
    verified = {"dish_id": "verified", "name": "Verified", "category": "test", "verified": True}
    distances = {"nearer": 0.1, "verified": 0.105}
    monkeypatch.setattr(substitutions, "renal_nutrient_distance", lambda a, b: distances[b["dish_id"]])
    monkeypatch.setattr(substitutions, "_mineral_load", lambda d: 0.0)
    ranked = substitutions.suggest_substitutions("query", dishes=[query, nearer, verified])
    assert [r["dish_id"] for r in ranked] == ["verified", "nearer"]
    assert ranked[0]["nutrient_distance"] > ranked[1]["nutrient_distance"]
    assert ranked[0]["ranking_score"] < ranked[1]["ranking_score"]
    assert ranked[0]["distance"] == ranked[0]["ranking_score"]


def test_historical_composite_retains_unweighted_term_and_serialized_key(monkeypatch):
    query = {"dish_id": "query", "name": "Query", "category": "test"}
    candidates = [{"dish_id": did, "name": did, "category": "test"} for did in ("plain", "renal")]
    monkeypatch.setattr(substitutions, "nutrient_distance", lambda a, b: 0.1 if b["dish_id"] == "plain" else 0.2)
    monkeypatch.setattr(substitutions, "renal_nutrient_distance", lambda a, b: 0.3 if b["dish_id"] == "plain" else 0.1)
    monkeypatch.setattr(substitutions, "_mineral_load", lambda d: 0.0)
    assert comparison._rank_by(query, candidates, "v2_composite") == ["plain", "renal"]
    production = substitutions.suggest_substitutions("query", dishes=[query, *candidates])
    assert [r["dish_id"] for r in production] == ["renal", "plain"]
