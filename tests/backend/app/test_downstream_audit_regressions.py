"""Regressions for KB history, catalogue recovery, adherence, and explanations.

Synthetic fixtures establish failure-path preconditions without changing stored
clinical history or depending on catalogue rankings that can change.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, get_type_hints

import pytest

from backend.app.adherence import analysis, store
from backend.app.api import adherence, dishes
from backend.app.explain.views import patient_explanation
from backend.app.kb.graph_store import KBGraph, load_kb
from backend.optim.real_data import load_dishes
from shared.envelope_schema import NutrientEnvelope

T1 = "2026-10-01T00:00:00+00:00"
T2 = "2026-10-08T00:00:00+00:00"


@pytest.fixture(autouse=True)
def isolated_database(pg_databases, monkeypatch):
    monkeypatch.setenv("CARELOOP_APP_DATABASE_URL", pg_databases["clinical"])


def envelope(version=1, envelope_id="ENV-P0001-test"):
    return NutrientEnvelope.model_validate({
        "envelope_id": envelope_id, "patient_id": "P0001", "version": version,
        "status": "APPROVED", "priority_basis": "test",
        "patient_snapshot": {"patient_id": "P0001", "age": 60, "sex": "M", "weight_kg": 70},
        "targets": [
            {"nutrient": "sodium_mg", "kind": "max", "value": 1000, "unit": "mg"},
            {"nutrient": "fiber_g", "kind": "min", "value": 30, "unit": "g"},
        ],
    })


class Dish:
    category = "test"
    tags: ClassVar[list] = []

    def __init__(self, dish_id, sodium, fiber=0):
        self.dish_id = self.name = dish_id
        self.values = {"sodium_mg": sodium, "fiber_g": fiber}

    def nutrient(self, key):
        return self.values.get(key, 0)


def rule(rule_id="R1", section="S1", url="one"):
    return {
        "rule_id": rule_id, "guideline": "Shared guideline", "section": section,
        "url": url, "conditions": [],
        "actions": [{"type": "set_constraint", "nutrient": "sodium_mg", "kind": "max", "value": 2000}],
    }


@pytest.fixture
def kb():
    graph = KBGraph()
    yield graph
    graph.close()


def test_shared_guideline_revision_retains_all_sections_and_history(kb):
    kb.append_rule(rule(), valid_from=T1)
    kb.append_rule(rule("R2", "S2", "two"), valid_from=T2)
    current_sections = {node["id"] for node in kb.nodes(label="Section")}
    attached = {edge["dst"] for edge in kb.edges() if edge["rel_type"] == "HAS_SECTION"}
    assert len(current_sections) == 2
    assert attached == current_sections
    historical = kb.edges(version=T1)
    assert len([edge for edge in historical if edge["rel_type"] == "HAS_SECTION"]) == 1
    assert kb.node_history("guideline:shared_guideline")[0]["props"]["url"] == "one"


def test_real_corpus_has_no_disconnected_current_sections():
    from backend.datasets.paths import dataset_path
    graph = load_kb(dataset_path("rules.json"), dataset_path("dishes.json"), valid_from=T1)
    try:
        sections = {node["id"] for node in graph.nodes(label="Section")}
        attached = {edge["dst"] for edge in graph.edges() if edge["rel_type"] == "HAS_SECTION"}
        assert sections and attached == sections
    finally:
        graph.close()


def test_snapshot_omits_later_edge_between_unchanged_endpoints(kb):
    kb.append_node("Test", "a", {}, valid_from=T1)
    kb.append_node("Test", "b", {}, valid_from=T1)
    kb.append_edge("LINK", "a", "b", valid_from=T2)
    assert len(kb.nodes(version=T1)) == 2
    assert kb.edges(version=T1) == []
    assert len(kb.edges(version=T2)) == 1


def test_identical_rule_reimport_is_idempotent(kb):
    original = rule()
    kb.append_rule(original, valid_from=T1)
    before = kb.stats(), kb.get_rule("R1"), kb.edges()
    assert kb.append_rule(deepcopy(original), valid_from=T2) == 1
    assert (kb.stats(), kb.get_rule("R1"), kb.edges()) == before
    assert len(kb.get_rule("R1")["constraints"]) == 1


def test_malformed_later_action_preserves_neighbourhood_and_retry(kb):
    kb.append_rule(rule(), valid_from=T1)
    before = kb.node_history("rule:R1"), kb.edges(), kb.stats()
    changed = rule(url="two")
    changed["actions"][0]["value"] = 1800
    changed["actions"].append({"type": "set_constraint", "nutrient": "fiber_g", "kind": "min"})
    with pytest.raises(ValueError):
        kb.append_rule(changed, valid_from=T2)
    assert (kb.node_history("rule:R1"), kb.edges(), kb.stats()) == before
    changed["actions"].pop()
    assert kb.append_rule(changed, valid_from=T2) == 2
    assert kb.get_rule("R1", version=1)["constraints"][0]["value"] == 2000
    assert kb.get_rule("R1")["constraints"][0]["value"] == 1800


def test_mid_append_failure_rolls_back_all_writes(kb, monkeypatch):
    kb.append_rule(rule(), valid_from=T1)
    before = kb.node_history("rule:R1"), kb.edges(), kb.stats()
    original = kb._append_edge

    def fail_produces(rel_type, *args, **kwargs):
        if rel_type == "PRODUCES":
            raise RuntimeError("injected write failure")
        return original(rel_type, *args, **kwargs)

    monkeypatch.setattr(kb, "_append_edge", fail_produces)
    changed = rule(url="two")
    changed["actions"][0]["value"] = 1800
    with pytest.raises(RuntimeError, match="injected"):
        kb.append_rule(changed, valid_from=T2)
    assert (kb.node_history("rule:R1"), kb.edges(), kb.stats()) == before
    monkeypatch.setattr(kb, "_append_edge", original)
    assert kb.append_rule(changed, valid_from=T2) == 2


@pytest.mark.parametrize("version, timestamp", [(1, T2), (3, T2), (4, T1)])
def test_node_rejects_nonmonotone_version_or_time_before_writes(kb, version, timestamp):
    kb.append_node("Test", "a", {"value": 1}, version=3, valid_from=T2)
    before = kb.node_history("a")
    with pytest.raises(ValueError):
        kb.append_node("Test", "a", {"value": 2}, version=version, valid_from=timestamp)
    assert kb.node_history("a") == before
    assert len(kb.nodes()) == 1
    assert kb.append_node("Test", "a", {"value": 2}, valid_from=T2) == 4


@pytest.mark.parametrize("bad", [None, "{broken", "null", "42", "{}", '{"dishes": {}}', '[null]', '[{}]'])
def test_catalogue_failures_are_503_and_recover_without_restart(client, tmp_path, monkeypatch, bad):
    catalogue = tmp_path / "dishes.json"
    if bad is not None:
        catalogue.write_text(bad)
    monkeypatch.setattr(dishes, "DISHES_FILE", catalogue)
    monkeypatch.setattr(dishes, "_DISH_CACHE", None)
    for path in ("/dishes", "/dishes/TEST"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "dish_database_unavailable"
    catalogue.write_text('[{"dish_id":"TEST","name":"Recovered","category":"test"}]')
    assert client.get("/dishes").json()["count"] == 1
    assert client.get("/dishes/TEST").json()["name"] == "Recovered"


@pytest.mark.parametrize("payload", [{"dish_id": ""}, {"dish_id": "  "}, {"items": [{"dish_id": ""}]}, {"items": [{"dish_id": " \t"}]}])
def test_blank_ids_cannot_create_complete_zero_nutrient_days(client, payload):
    for meal in store.MEALS:
        response = client.post("/adherence/log", json={
            "patient_id": "P0001", "date": datetime.now(UTC).date().isoformat(), "meal": meal, **payload,
        })
        assert response.status_code == 422
    assert store.count_logs("P0001") == 0


def test_postponed_annotations_resolve():
    for target in (analysis.day_totals, store.count_logs, adherence._envelope_notice, adherence._resolve_day_envelopes):
        assert get_type_hints(target)


def test_aggregate_owner_matches_single_and_mixed_classified_days():
    env = envelope()
    dish_map = {"A": Dish("A", 1200, 4)}
    logs = [{"date": "2026-01-01", "meal": meal, "dish_id": "A"} for meal in store.MEALS]
    logs.append({"date": "2026-01-02", "meal": "lunch", "dish_id": "A"})
    ranged = analysis.analyse_range(logs, env, dish_map)
    assert analysis.aggregate_days(ranged["days"]) == ranged["aggregate"]
    assert analysis.aggregate_days([]) == analysis.analyse_range([], env, dish_map)["aggregate"]
    assert ranged["aggregate"]["hard_violations_by_nutrient"] == {"sodium_mg": 2}
    assert ranged["aggregate"]["soft_gaps_by_nutrient"] == {"fiber_g": 1}
    assert ranged["aggregate"]["fraction_complete"] == 0.5
    second = envelope(version=2)
    second.targets[0].value = 2000
    mixed_days = [ranged["days"][0], analysis.analyse_range(logs[-1:], second, dish_map)["days"][0]]
    mixed = analysis.aggregate_days(mixed_days)
    assert mixed["hard_violation_days"] == 1
    assert mixed["mean_pct_deviation_by_nutrient"] == ranged["aggregate"]["mean_pct_deviation_by_nutrient"]


@pytest.mark.parametrize("group_count", [0, 1, 2])
def test_summary_response_preserves_shared_aggregate_rounding_and_empty_policy(client, monkeypatch, group_count):
    env = envelope()
    dish_map = {"A": Dish("A", 1234.56789, 4.12345)}
    groups: list[dict[str, Any]] = []
    for index in range(group_count):
        day = (datetime.now(UTC).date() - timedelta(days=index)).isoformat()
        assigned = envelope(version=index + 1)
        entries = [{"date": day, "meal": meal, "dish_id": "A"} for meal in store.MEALS]
        result = analysis.analyse_range(entries, assigned, dish_map)
        groups.append({"envelope": assigned, "dates": [day], "result": result})
    attributed = {"groups": groups, "unattributed_days": [], "latest": env}
    monkeypatch.setattr(adherence, "find_latest_envelope_for_patient", lambda patient_id: env)
    monkeypatch.setattr(adherence, "attributed_analysis", lambda *args, **kwargs: attributed)
    response = client.get("/adherence/P0001/summary")
    assert response.status_code == 200
    body = response.json()
    expected_days = sorted([day for group in groups for day in group["result"]["days"]], key=lambda day: day["date"])
    assert body["days"] == expected_days
    assert body["aggregate"] == analysis.aggregate_days(expected_days)
    assert body["days_logged"] == group_count
    if group_count:
        assert body["aggregate"]["mean_pct_deviation_by_nutrient"]["sodium_mg"] == 270.3704
    else:
        assert body["aggregate"]["fraction_complete"] == 0


@pytest.mark.parametrize("same_identity", [False, True])
def test_historical_flags_join_exact_merged_series_identity(client, monkeypatch, same_identity):
    first = envelope()
    second = envelope(version=2, envelope_id=first.envelope_id if same_identity else "ENV-P0001-other")
    day_map = {}
    logs = []
    dish_map = {"ZERO": Dish("ZERO", 0)}
    for index in range(6):
        day = (datetime.now(UTC).date() - timedelta(days=5-index)).isoformat()
        day_map[day] = first if index < 3 else second
        dish_id = f"D{index}"
        dish_map[dish_id] = Dish(dish_id, 1100 + (index % 3) * 100)
        logs.extend({"date": day, "meal": meal, "dish_id": dish_id if meal == "lunch" else "ZERO"} for meal in store.MEALS)
    monkeypatch.setattr(adherence.persistence, "envelope_effective_at", lambda patient_id, day: day_map[day])
    monkeypatch.setattr(adherence, "find_latest_envelope_for_patient", lambda patient_id: second)
    monkeypatch.setattr(adherence.store, "list_logs", lambda *args, **kwargs: logs)
    monkeypatch.setattr(adherence, "_dish_index", lambda: dish_map)
    response = client.get("/adherence/P0001/deviation").json()
    flags = response["flags"]
    assert len(flags) == 2
    assert len({flag["series_key"] for flag in flags}) == 2
    for flag in flags:
        key = flag["series_key"]
        assert key in response["series"]
        assert flag["direction"] == "worsening"
        expected_prefix = flag["envelope_id"] + (f"::v{flag['envelope_version']}" if same_identity else "")
        assert key == expected_prefix + "::sodium_mg"


def test_serving_adjustment_changes_contributor_order_amounts_and_shares():
    dish_map = {"A": Dish("A", 600, 4), "B": Dish("B", 300, 10), "C": Dish("C", 100, 5)}
    entries = [
        {"meal": "breakfast", "items": [{"dish_id": "A", "quantity": 0.5}]},
        {"meal": "lunch", "items": [{"dish_id": "B", "quantity": 2}]},
        {"meal": "dinner", "dish_id": "C"},
    ]
    result = analysis.analyse_day("2026-01-01", entries, envelope(), dish_map)
    rows = {row["nutrient"]: row for row in result["nutrients"]}
    sodium = rows["sodium_mg"]["contributors"]
    assert [item["dish_id"] for item in sodium] == ["B", "A"]
    assert [item["amount"] for item in sodium] == [600, 300]
    assert [item["pct_of_day_total"] for item in sodium] == [60, 30]
    fiber = rows["fiber_g"]["contributors"]
    assert [item["dish_id"] for item in fiber] == ["A", "C"]
    assert [item["amount"] for item in fiber] == [2, 5]
    assert fiber[0]["pct_of_day_total"] == pytest.approx(2 / 27 * 100, abs=0.0001)
    assert result["completeness"]["complete"]


def test_incomplete_days_never_invoke_slope_estimation(monkeypatch):
    env = envelope()
    dish_map = {"A": Dish("A", 1200)}
    logs = [{"date": f"2026-01-0{i}", "meal": "lunch", "dish_id": "A"} for i in range(1, 5)]
    def unexpected_slope(*args):
        pytest.fail("incomplete days entered slope estimation")
    monkeypatch.setattr(analysis, "_theil_sen_slope", unexpected_slope)
    result = analysis.analyse_patient(logs, env, dish_map)
    assert result["aggregate"]["complete_days"] == 0
    assert result["flags"] == []


def test_edited_legacy_values_cannot_borrow_guideline_mentions():
    env = envelope().model_dump(mode="json")
    targets: list[dict[str, Any]] = [{"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"}]
    env["targets"] = targets
    guideline = {"rule_id": "GUIDELINE", "guideline": "KDIGO", "section": "sodium"}
    env["fired_rules"] = [{"rule_id": "GUIDELINE", "priority": 90,
                           "action_summary": "set sodium_mg max = 2000 mg/d", "citation": guideline}]
    assert patient_explanation(env)["why"] == []
    env["fired_rules"].append({"rule_id": "CLINICIAN-EDIT", "priority": 0,
                              "action_summary": "set sodium_mg max = 1800 mg/d",
                              "citation": {"rule_id": "CLINICIAN-EDIT", "guideline": "clinician override"}})
    assert patient_explanation(env)["why"] == ["Your care team set: keep sodium under 1.8 g a day."]
    # Explicit but stale provenance is not superseded by a convenient trace match.
    env["targets"][0]["provenance"] = {**env["targets"][0], "value": 2000, "citation": guideline}
    assert patient_explanation(env)["why"] == []


def test_mixed_bound_authorship_is_not_collapsed_to_one_source():
    env = envelope().model_dump(mode="json")
    targets: list[dict[str, Any]] = [
        {"nutrient": "protein_g", "kind": "min", "value": 40, "unit": "g"},
        {"nutrient": "protein_g", "kind": "max", "value": 60, "unit": "g"},
    ]
    env["targets"] = targets
    for target, source, guideline in zip(env["targets"], ["CLINICIAN-EDIT", "RULE"], ["clinician override", "KDIGO"]):
        target["provenance"] = {**target, "citation": {"rule_id": source, "guideline": guideline}}
    why = patient_explanation(env)["why"]
    assert why == ["Your care team set: get at least 40 g of protein a day.",
                   "KDIGO recommends: keep protein under 60 g a day."]
    assert patient_explanation(env)["daily_targets"][0]["text"] == "Aim for 40 g to 60 g of protein a day."


@pytest.mark.parametrize("kind", ["min", "max"])
def test_patient_bounds_preserve_more_than_six_significant_digits(kind):
    env = envelope().model_dump(mode="json")
    env["targets"] = [{"nutrient": "sodium_mg", "kind": kind, "value": 1555.123456, "unit": "mg"}]
    text = patient_explanation(env)["daily_targets"][0]["text"]
    assert "1555.123456 mg" in text


def test_p0006_exclusion_blocks_candidate_that_enters_ranking(client, monkeypatch):
    from backend.mining import patient_swaps
    from backend.optim.problem import exclusion_for

    response = client.post("/rules/run", json={"patient_id": "P0006"})
    assert response.status_code == 200
    env = NutrientEnvelope.model_validate(response.json()["envelope"])
    # Remove competing nutrient failures only in this local evaluation fixture;
    # the real patient exclusions remain the property under test.
    for target in env.targets:
        if target.kind.value == "max":
            target.value = 1_000_000
    catalogue = load_dishes()
    lookup = {dish.dish_id: dish for dish in catalogue}
    assert exclusion_for(lookup["SG0030"], env) is not None
    document = {"days": [{"day": 1, "slots": [{"meal": meal, "dish_id": "SG0009"} for meal in store.MEALS]}]}
    calls = []
    def ranked_candidate(dish_id, k, version):
        calls.append((dish_id, k, version))
        return [{"dish_id": "SG0030", "name": "Curry Mee"}]
    monkeypatch.setattr(patient_swaps, "suggest_substitutions", ranked_candidate)
    control = env.model_copy(deep=True)
    control.exclusions = []
    admitted = patient_swaps.patient_substitutions("SG0009", 1, control, document, catalogue)
    assert [item["dish_id"] for item in admitted["substitutions"]] == ["SG0030"]
    filtered = patient_swaps.patient_substitutions("SG0009", 1, env, document, catalogue)
    assert filtered["candidates_evaluated"] == 1
    assert filtered["substitutions"] == []
    assert calls == [("SG0009", 3, 2), ("SG0009", 3, 2)]
