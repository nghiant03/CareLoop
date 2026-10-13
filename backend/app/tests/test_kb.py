"""Check catalogue queries, historical KB snapshots, and SQL immutability guards."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.app.kb.graph_store import KBGraph, load_kb

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

RULES_PATH = dataset_path("rules.json")
DISHES_PATH = dataset_path("dishes.json")

# Timestamps pinned by the tests so point-in-time snapshots are deterministic.
T1 = "2026-10-01T00:00:00+00:00"
T2 = "2026-10-08T00:00:00+00:00"


@pytest.fixture(scope="module")
def kb() -> Iterator[KBGraph]:
    graph = load_kb(RULES_PATH, DISHES_PATH, valid_from=T1)
    yield graph
    graph.close()


def test_load_real_content_counts(kb: KBGraph) -> None:
    stats = kb.stats()
    # Keep a minimum rule-coverage check without fixing the growing rule count;
    # dish/profile counts must match the benchmark corpus exactly.
    assert stats["node_counts"]["Rule"] >= 50
    assert stats["node_counts"]["Dish"] == 214
    assert stats["node_counts"]["NutrientProfile"] == 214
    assert stats["node_counts"]["Guideline"] >= 5
    assert stats["edge_counts"]["HAS_PROFILE"] == 214
    assert stats["edge_counts"]["CITES"] == stats["node_counts"]["Rule"]


def test_rule_nodes_carry_source_and_version(kb: KBGraph) -> None:
    for node in kb.nodes(label="Rule"):
        assert node["source"], f"rule {node['id']} missing source"
        assert node["version"] >= 1
        assert node["checksum"]
        assert node["valid_from"] == T1 and node["valid_to"] is None


def test_current_version(kb: KBGraph) -> None:
    assert kb.current_version() == T1


def test_get_rule_current(kb: KBGraph) -> None:
    rule = kb.get_rule("CKD-2024-SODIUM-2000")
    assert rule is not None
    assert rule["priority"] == 90
    assert rule["guideline"] == "KDIGO 2024 CKD Guideline"
    assert rule["section"] == "Sec. 3.4 / Dietary Sodium"
    assert rule["verbatim_quote"] == "recommend sodium intake less than 2 g per day"
    kinds = [(c["nutrient"], c["kind"], c["value"]) for c in rule["constraints"]]
    assert ("sodium_mg", "max", 2000) in kinds


def test_get_rule_unknown(kb: KBGraph) -> None:
    assert kb.get_rule("NOPE-0000-XYZ") is None


def test_rules_for_nutrient(kb: KBGraph) -> None:
    rule_ids = [r["rule_id"] for r in kb.rules_for_nutrient("sodium_mg")]
    assert "CKD-2024-SODIUM-2000" in rule_ids
    assert "DASH-2025-SODIUM-2300" in rule_ids
    assert "ADA-2026-SODIUM-2300" in rule_ids
    # Ordered by priority DESC: the CKD p90 rule must come before DASH p70.
    assert rule_ids.index("CKD-2024-SODIUM-2000") < rule_ids.index(
        "DASH-2025-SODIUM-2300"
    )


def test_rules_for_nutrient_unknown(kb: KBGraph) -> None:
    assert kb.rules_for_nutrient("unobtanium_mg") == []


def test_dishes_meeting_max(kb: KBGraph) -> None:
    dishes = kb.dishes_meeting({"nutrient": "sodium_mg", "kind": "max", "value": 200})
    assert dishes, "expected some dishes under 200 mg sodium"
    for dish in dishes:
        assert dish["profile"]["sodium_mg"] <= 200
    # Closest-to-ceiling first (deterministic ordering).
    sodiums = [d["profile"]["sodium_mg"] for d in dishes]
    assert sodiums == sorted(sodiums, reverse=True)


def test_dishes_meeting_min(kb: KBGraph) -> None:
    dishes = kb.dishes_meeting({"nutrient": "protein_g", "kind": "min", "value": 40})
    assert dishes
    for dish in dishes:
        assert dish["profile"]["protein_g"] >= 40


def test_dishes_meeting_impossible(kb: KBGraph) -> None:
    dishes = kb.dishes_meeting({"nutrient": "sodium_mg", "kind": "max", "value": 0})
    assert dishes == []


def test_graph_snapshot(kb: KBGraph) -> None:
    g = kb.graph()
    assert g.number_of_nodes() >= 214 + 50
    assert g.number_of_edges() >= 214 * 2
    rule_node = g.nodes["rule:CKD-2024-SODIUM-2000"]
    assert rule_node["label"] == "Rule"
    assert rule_node["priority"] == 90
    # Rule --CITES--> Section --(reverse of HAS_SECTION)--> Guideline chain.
    cites = list(g.edges(("rule:CKD-2024-SODIUM-2000"), keys=True))
    assert any(key == "CITES" for _, _, key in cites)
    assert any(key == "PRODUCES" for _, _, key in cites)


def test_version_edit_and_point_in_time() -> None:
    kb = load_kb(RULES_PATH, DISHES_PATH, valid_from=T1)
    try:
        old = kb.get_rule("CKD-2024-SODIUM-2000")
        assert old is not None
        assert old["version"] == 1

        # Tighten the rule: 2000 -> 1800 mg ceiling, issued at T2.
        edited = json.loads(json.dumps(old))
        edited["actions"] = [
            {**a, "value": 1800}
            if a.get("type") == "set_constraint"
            else a
            for a in edited["actions"]
        ]
        new_version = kb.append_rule(edited, valid_from=T2)
        assert new_version == 2

        # Current read sees the new value; explicit version read sees the old.
        current = kb.get_rule("CKD-2024-SODIUM-2000")
        assert current is not None
        assert current["version"] == 2
        assert current["constraints"][0]["value"] == 1800
        assert current["constraints"][0]["version"] == 2

        historical = kb.get_rule("CKD-2024-SODIUM-2000", version=1)
        assert historical is not None
        assert historical["version"] == 1
        assert historical["constraints"][0]["value"] == 2000
        assert historical["valid_to"] == T2  # closed by the new version

        # History is complete and ordered.
        history = kb.node_history("rule:CKD-2024-SODIUM-2000")
        assert [h["version"] for h in history] == [1, 2]
        assert history[0]["props"]["priority"] == 90

        # Point-in-time graphs: T1 shows the old ceiling, T2 the new one.
        g1 = kb.graph(version=T1)
        v1 = g1.nodes["constraint:CKD-2024-SODIUM-2000:sodium_mg:max"]["value"]
        assert v1 == 2000
        g2 = kb.graph(version=T2)
        v2 = g2.nodes["constraint:CKD-2024-SODIUM-2000:sodium_mg:max"]["value"]
        assert v2 == 1800
        assert kb.current_version() == T2
    finally:
        kb.close()


def test_append_only_no_content_row_updates() -> None:
    kb = load_kb(RULES_PATH, DISHES_PATH, valid_from=T1)
    try:
        before = kb.node_history("rule:CKD-2024-SODIUM-2000")
        edited = json.loads(json.dumps(kb.get_rule("CKD-2024-SODIUM-2000")))
        for action in edited["actions"]:
            if action.get("type") == "set_constraint":
                action["value"] = 1500
        kb.append_rule(edited, valid_from=T2)

        # Every history row is still present with byte-identical content; the
        # only permitted change is the closing `valid_to` on the old version.
        after = kb.node_history("rule:CKD-2024-SODIUM-2000")
        assert [h["version"] for h in after] == [1, 2]
        assert after[0]["props"] == before[0]["props"]
        assert after[0]["checksum"] == before[0]["checksum"]
        assert after[0]["label"] == before[0]["label"]
        assert after[0]["source"] == before[0]["source"]
        assert after[0]["valid_from"] == before[0]["valid_from"]
        assert after[0]["valid_to"] == T2

        # A raw UPDATE of node content must abort (SQL trigger).
        with pytest.raises(Exception, match="append-only"):
            kb._conn.execute(
                "UPDATE nodes SET props = '{}' WHERE logical_id = 'rule:CKD-2024-SODIUM-2000'"
            )
        # Edges are fully immutable — any UPDATE aborts.
        with pytest.raises(Exception, match="append-only"):
            kb._conn.execute("UPDATE edges SET rel_type = 'X'")

        # The failed updates did not corrupt anything.
        current = kb.get_rule("CKD-2024-SODIUM-2000")
        assert current is not None
        assert current["priority"] == 90
    finally:
        kb.close()


def test_stats_shape(kb: KBGraph) -> None:
    stats = kb.stats()
    assert set(stats) == {
        "db_path", "current_version", "node_counts", "edge_counts",
    }
    assert stats["current_version"] == T1
    assert sum(stats["node_counts"].values()) >= 214 + 50
