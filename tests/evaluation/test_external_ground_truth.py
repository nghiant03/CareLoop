"""Tests for independent external ground-truth evaluations, SG FoodID staging, and OpenAI-compatible extraction."""

from __future__ import annotations

import json

from backend.app.chat.llm import OpenAICompatLLM, build_openai_compat_adapter
from backend.datasets.paths import dataset_dir, dataset_path
from backend.datasets.research_transform import (
    load_sgfoodid_candidates,
    parse_sgfoodid_num,
)
from backend.knowledge.discovery import (
    evaluate_cross_guideline_ground_truth,
    extract_rules_openai_compat,
    verify_quote_in_source,
)
from evaluation.external import (
    _evaluate_eicu,
    _evaluate_milp_and_sgfoodid,
    _evaluate_uci_cohorts,
)


def test_sgfoodid_never_coerces_dash_to_zero():
    assert parse_sgfoodid_num("-") is None
    assert parse_sgfoodid_num(" - ") is None
    assert parse_sgfoodid_num("") is None
    assert parse_sgfoodid_num(None) is None
    assert parse_sgfoodid_num("125.5") == 125.5
    assert parse_sgfoodid_num("1,240") == 1240.0


def test_sgfoodid_catalogue_audit_and_completeness():
    raw_root = dataset_dir() / "research" / "raw"
    res = load_sgfoodid_candidates(raw_root)
    assert res["available"] is True
    assert res["total_rows"] == 2689
    assert res["complete_10_nutrient_rows"] >= 527
    assert res["incomplete_excluded_rows"] == res["total_rows"] - res["complete_10_nutrient_rows"]
    ext = res["extended_nutrient_coverage_in_complete_subset"]
    assert ext["calcium_mg"]["rate"] >= 0.99
    assert ext["iron_mg"]["rate"] == 1.0
    assert ext["water_g"]["rate"] >= 0.99
    for rec in res["complete_records"]:
        assert rec["missing_nutrients"] == []
        assert all(v is not None for v in rec["nutrients"].values())


def test_openai_compat_rule_extraction_verifies_verbatim_quotes():
    passage = (
        "Recommendation 3.3.2.1: We suggest that sodium intake be <2 g of sodium per day "
        "(or <90 mmol of sodium per day, or <5 g of sodium chloride per day) in people with CKD (2C)."
    )
    assert verify_quote_in_source("We suggest that sodium intake be <2 g of sodium per day", passage) is True
    assert verify_quote_in_source("Sodium intake must be <1.2 g per day in all adults", passage) is False
    assert verify_quote_in_source("", passage) is False

    class FakeOpenAIClient:
        def chat_completion(self, messages, temperature=0.0, json_mode=False):
            assert json_mode is True
            assert temperature == 0.0
            return json.dumps({
                "candidates": [
                    {
                        "section": "3.3.2.1",
                        "nutrient": "sodium_mg",
                        "kind": "MAX",
                        "value": 2000.0,
                        "basis": "mg_per_day",
                        "quote": "We suggest that sodium intake be <2 g of sodium per day",
                        "source_population": "People with CKD",
                        "caveats": ["sodium-wasting nephropathy"],
                    },
                    {
                        "section": "9.9.9",
                        "nutrient": "sodium_mg",
                        "kind": "MAX",
                        "value": 1200.0,
                        "basis": "mg_per_day",
                        "quote": "Hallucinated quote that is not in the source text",
                        "source_population": "People with CKD",
                    },
                ]
            })

    extracted = extract_rules_openai_compat(passage, {"guideline": "KDIGO 2024 CKD"}, FakeOpenAIClient())
    assert len(extracted) == 1
    cand = extracted[0]
    assert cand["status"] == "NEEDS_REVIEW"
    assert cand["automatic_activation_allowed"] is False
    assert cand["suggested_constraint"]["nutrient"] == "sodium_mg"
    assert cand["suggested_constraint"]["value"] == 2000.0
    assert cand["evidence"][0]["verified_substring"] is True

    adapter = build_openai_compat_adapter(
        env={"CARELOOP_OPENAI_BASE_URL": "http://localhost:8000/v1", "OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "gpt-4o-mini"}
    )
    assert isinstance(adapter, OpenAICompatLLM)
    assert adapter.base_url == "http://localhost:8000/v1"
    assert adapter.model == "gpt-4o-mini"


def test_cross_guideline_and_milp_and_eicu_and_uci_oracles():
    raw_root = dataset_dir() / "research" / "raw"
    rules_doc = json.loads(dataset_path("rules.json").read_text(encoding="utf-8"))

    gt = evaluate_cross_guideline_ground_truth(raw_root.parent, rules_doc)
    assert gt["available"] is True
    assert gt["society_polarity_concordance_rate"] == 1.0
    assert gt["fda_interaction_concordance_rate"] == 1.0

    milp_res = _evaluate_milp_and_sgfoodid(raw_root)
    assert milp_res["milp_global_optimum_oracle"]["max_abs_discrepancy_vs_exact"] == 0.0
    assert milp_res["counterfactual_substitution_oracle"]["high_risk_dish_queries"] > 100

    eicu_res = _evaluate_eicu(raw_root)
    assert eicu_res["available"] is True
    assert eicu_res["icu_stays_total"] == 2520
    assert eicu_res["distinct_hospitals"] > 150
    assert eicu_res["prefix_forecast_benchmark"]["combined"]["episodes"] == 1300

    uci_res = _evaluate_uci_cohorts(raw_root)
    assert uci_res["uci_ckd"]["available"] is True
    assert uci_res["uci_ckd"]["evaluated_subjects"] == 400
    assert uci_res["uci_diabetes_130_hospitals"]["available"] is True
    assert uci_res["uci_diabetes_130_hospitals"]["encounters_with_measured_a1c_sampled"] > 2000
