"""Deterministic tests for the retrieval benchmark (backend/app/chat).

Verifies: the labeled query set loads and its expected chunk ids resolve to
real chunks; the benchmark runs with sane, consistent metrics; the as-is
method reproduces production retrieval behaviour exactly; the run is
deterministic across two evaluations; and the artifact is written and parses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.chat import retrieval, retrieval_bench
from backend.app.kb.graph_store import load_kb

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "rules" / "rules.json"
DISHES_PATH = _REPO_ROOT / "data" / "dishes.json"


@pytest.fixture(scope="module")
def kb():
    graph = load_kb(RULES_PATH, DISHES_PATH)
    yield graph
    graph.close()


@pytest.fixture(scope="module")
def results(kb):
    return retrieval_bench.evaluate(kb)


# ---------------------------------------------------------------------------
# Labeled set
# ---------------------------------------------------------------------------


def test_labeled_set_loads_with_expected_size_and_categories(kb):
    queries = retrieval_bench.labeled_queries(kb)
    assert len(queries) >= 40
    categories = {q["category"] for q in queries}
    assert {"guideline_nutrient", "dish", "conflict", "variant_typo",
            "topic"} <= categories
    for q in queries:
        assert q["id"] and q["query"].strip()
        assert q["relevant"], f"no relevant ids for {q['id']}"
        assert all(
            cid.startswith(("rule:", "dish:")) for cid in q["relevant"]
        ), q["id"]


def test_expected_chunk_ids_resolve_to_real_chunks(kb):
    queries = retrieval_bench.labeled_queries(kb)
    prod_index = retrieval.build_index(kb)
    chunk_ids = {c["chunk_id"] for c in prod_index.chunks}
    for q in queries:
        missing = set(q["relevant"]) - chunk_ids
        assert not missing, f"{q['id']}: unknown chunk ids {missing}"


# ---------------------------------------------------------------------------
# Bench run + metrics sanity
# ---------------------------------------------------------------------------


def test_bench_metrics_are_sane(results):
    methods = results["methods"]
    assert len(methods) >= 4
    names = {m["name"] for m in methods}
    # All four required families present, with and without synonym expansion.
    for family in ("tfidf_word_asis", "tfidf_word_sublinear",
                   "tfidf_char_wb_3_5", "bm25_word"):
        assert f"{family}_syn" in names
        assert f"{family}_nosyn" in names
    for m in methods:
        for key in ("hit@1", "hit@3", "hit@5", "mrr"):
            assert 0.0 <= m[key] <= 1.0, (m["name"], key)
        assert m["hit@1"] <= m["hit@3"] + 1e-9 <= m["hit@5"] + 1e-9, m["name"]
        assert m["mrr"] >= m["hit@1"] - 1e-9, m["name"]  # MRR >= hit@1
        for cat_metrics in m["by_category"].values():
            assert 0.0 <= cat_metrics["mrr"] <= 1.0


def test_bench_at_least_one_method_retrieves_something(results):
    # Not every query can be hopeless for every method — catches a broken
    # index build (e.g. empty corpus or inverted ranking).
    best = max(results["methods"], key=lambda m: m["mrr"])
    assert best["mrr"] > 0.5, best["name"]


def test_ranking_is_consistent_with_metrics(results):
    ranked = results["ranking"]
    assert ranked == sorted(
        ranked,
        key=lambda name: next(
            (-m["mrr"], -m["hit@5"], -m["hit@1"], m["name"])
            for m in results["methods"] if m["name"] == name
        ),
    )
    assert results["winner"] == ranked[0]


def test_production_method_matches_production_retrieval(kb):
    methods = retrieval_bench.build_methods(kb)
    prod_index = retrieval.build_index(kb)
    # Production switched to BM25: the production row is ``bm25_word_syn``
    # (the ``tfidf_word_asis_syn`` row is the previous TF-IDF scorer, kept
    # for comparison — it no longer matches production).
    as_is = methods[retrieval_bench.PROD_NAME]
    for query in (
        "How much sodium can I have per day?",
        "how much soduim per day",
        "sodium content of chicken rice",
        "What is the weather forecast for tomorrow?",
    ):
        assert as_is.retrieve(query, k=5) == prod_index.retrieve(query, k=5)


def test_end_to_end_spot_check_shape(results):
    e2e = results["end_to_end"]
    assert len(e2e["detail"]["questions"]) == 10
    assert e2e["summary"]  # every method scored
    for name, stats in e2e["summary"].items():
        assert 0.0 <= stats["citation_accuracy"] <= 1.0, name
        assert 0 <= stats["answered"] <= 10, name
    # The production pipeline keeps answering the grounded nutrient questions
    # regardless of retriever (anchor-rule path) — sanity floor.
    assert e2e["summary"]["tfidf_word_asis_syn"]["citation_accuracy"] >= 0.7


# ---------------------------------------------------------------------------
# Determinism + artifact
# ---------------------------------------------------------------------------


def test_bench_is_deterministic_across_runs(kb, results):
    again = retrieval_bench.evaluate(kb)
    assert json.dumps(results, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_artifact_written_and_parses(kb, tmp_path):
    results, path = retrieval_bench.run_bench(kb)
    path = retrieval_bench.write_results(results, path=tmp_path / "results.json")
    assert path.exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["queries"]["total"] >= 40
    assert parsed["winner"] in {m["name"] for m in parsed["methods"]}
    for m in parsed["methods"]:
        assert {"hit@1", "hit@3", "hit@5", "mrr"} <= set(m)


def test_main_cli_exits_zero(kb, capsys):
    exit_code = retrieval_bench.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "hit@1" in out and "MRR" in out and "Winner" in out