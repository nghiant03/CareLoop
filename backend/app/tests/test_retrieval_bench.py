"""Deterministic tests for the retrieval benchmark (backend/app/chat).

Obligations, grouped:

* **Labeled set**: the query set loads with expected size/categories and its
  expected chunk ids resolve to real production chunks.
* **Ranking/fusion**: benchmark metrics are sane and consistently ranked.
  The fusion row fuses the union of its components' candidates. The production
  row matches production retrieval while as-is TF-IDF stays a comparator.
* **Fusion gate**: the held-out diagnostic runs standalone with an unset gate
  and is recorded in the results; irrelevant questions are refused end to end.
* **State/determinism**: a bench run leaves ``retrieval.build_index`` and
  ``retrieval.MIN_SCORE`` module state untouched and is deterministic across
  two evaluations.
* **Artifacts**: benchmark and CLI runs write real artifacts (JSON + Markdown)
  to redirected temporary paths, never into the repository.
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


def test_best_method_mrr_above_0_5(results):
    # Not every query can be hopeless for every method — the best method's
    # MRR must exceed 0.5, catching a broken index build (e.g. empty corpus
    # or inverted ranking).
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
    production_method = methods[retrieval_bench.PROD_NAME]
    for query in (
        "How much sodium can I have per day?",
        "how much soduim per day",
        "sodium content of chicken rice",
        "What is the weather forecast for tomorrow?",
    ):
        assert production_method.retrieve(query, k=5) == prod_index.retrieve(query, k=5)


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
# RRF fusion row (bm25_rrf_char)
# ---------------------------------------------------------------------------


def test_fusion_row_present_with_sane_metrics(results):
    names = {m["name"] for m in results["methods"]}
    assert "bm25_rrf_char" in names
    fusion = next(m for m in results["methods"] if m["name"] == "bm25_rrf_char")
    for key in ("hit@1", "hit@3", "hit@5", "mrr"):
        assert 0.0 <= fusion[key] <= 1.0, key
    assert fusion["hit@1"] <= fusion["hit@3"] + 1e-9 <= fusion["hit@5"] + 1e-9
    assert fusion["mrr"] >= fusion["hit@1"] - 1e-9
    assert set(fusion["by_category"]) == {
        "guideline_nutrient", "dish", "conflict", "topic", "variant_typo"
    }


def test_fusion_fuses_the_union_of_component_candidates(kb):
    # RRF must fuse the UNION of the components' top-50 candidates (a chunk
    # found by only one component still contributes) — not rerank BM25 hits.
    methods = retrieval_bench.build_methods(kb)
    fusion = methods["bm25_rrf_char"]
    bm25 = methods[retrieval_bench.PROD_NAME]
    char = methods["tfidf_char_wb_3_5_syn"]
    for query in ("how much soduim per day", "is nasi lemak high in salt",
                  "wat is teh capitl of frnace"):
        fused_ids = {h["chunk_id"] for h in fusion.retrieve(query, k=100)}
        bm25_ids = {h["chunk_id"] for h in bm25.retrieve(query, k=50)}
        char_ids = {h["chunk_id"] for h in char.retrieve(query, k=50)}
        assert fused_ids == bm25_ids | char_ids, query


def test_fusion_retrieval_is_deterministic(kb):
    fusion = retrieval_bench.build_methods(kb)["bm25_rrf_char"]
    for query in ("how much soduim per day", "fibre in the mushroom corn oat porridge"):
        first = [h["chunk_id"] for h in fusion.retrieve(query, k=5)]
        second = [h["chunk_id"] for h in fusion.retrieve(query, k=5)]
        assert first == second
        scores = [h["score"] for h in fusion.retrieve(query, k=5)]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Fusion calibration + irrelevant refusal
# ---------------------------------------------------------------------------


def test_fusion_calibration_recorded(results):
    cal = results["fusion_calibration"]
    assert cal["threshold"] == results["threshold_calibration"]["bm25_rrf_char"]["threshold"]
    probes = retrieval_bench._irrelevant_probes()
    assert set(cal["irrelevant_probes"]) == set(probes)
    assert cal["irrelevant_best_score"] >= 0.0
    # Documented outcome: the RRF-score distributions overlap — no threshold
    # separates irrelevant from relevant queries (typo'd nonsense scores above
    # the weakest labeled-relevant query). This is the recorded reason the
    # fusion row is not the production default.
    assert cal["gap_ok"] is False
    assert cal["irrelevant_best_score"] >= cal["weakest_relevant"]["best_score"]


def test_fusion_diagnostic_standalone_with_unset_gate(kb):
    """Regression (unset threshold): ``min_score`` exists but is None before
    ``calibrate_methods`` runs, so a standalone diagnostic must not raise
    (TypeError on float < None) and must fall back to the documented default
    without ever selecting a gate from the held-out data."""
    fusion = retrieval_bench.build_methods(kb)["bm25_rrf_char"]
    assert fusion.min_score is None
    report = retrieval_bench.diagnose_fusion_gate(kb, fusion)
    assert report["threshold"] == retrieval_bench.FUSION_MIN_SCORE
    assert isinstance(report["gap_ok"], bool)
    # The diagnostic never mutates the method's gate.
    assert fusion.min_score is None


def test_fusion_diagnostic_retains_historical_aliases():
    # Callable alias and serialized key keep older callers/artifact readers
    # working; the diagnostic itself gained the accurate name.
    assert retrieval_bench.calibrate_fusion is retrieval_bench.diagnose_fusion_gate


def test_irrelevant_questions_refused_end_to_end(results):
    for name in (retrieval_bench.PROD_NAME, "bm25_rrf_char"):
        stats = results["irrelevant_refusal"][name]
        assert stats["probes"] == len(retrieval_bench._irrelevant_probes())
        assert stats["refused"] == stats["probes"], name
        assert all(r["status"] == "refused" for r in stats["rows"]), name


def test_bench_e2e_restores_retrieval_module_state(kb):
    # Each calibrated method temporarily replaces the index and refusal gate.
    # Both must be restored before the deployed pipeline handles another call.
    original_build_index = retrieval.build_index
    original_min_score = retrieval.MIN_SCORE
    try:
        retrieval_bench.evaluate(kb)
        assert retrieval.build_index is original_build_index
        assert retrieval.MIN_SCORE == original_min_score
        # The restored pipeline still refuses irrelevant questions.
        response = retrieval_bench._answer_with_method(
            retrieval_bench.ProductionMethod(
                retrieval.build_index(kb), retrieval_bench.PROD_NAME
            ),
            kb,
            "What is the capital of France?",
        )
        assert response["status"] == "refused"
    finally:
        retrieval.build_index = original_build_index
        retrieval.MIN_SCORE = original_min_score


# ---------------------------------------------------------------------------
# Determinism + artifact
# ---------------------------------------------------------------------------


def test_bench_is_deterministic_across_runs(kb, results):
    again = retrieval_bench.evaluate(kb)
    assert json.dumps(results, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_artifact_written_and_parses(kb, tmp_path, monkeypatch):
    # Redirect both artifact destinations (JSON + Markdown) before invocation:
    # the benchmark still performs its real generation, but tests must never
    # write outputs into the repository.
    monkeypatch.setattr(retrieval_bench, "RESULTS_PATH", tmp_path / "results.json")
    results, path = retrieval_bench.run_bench(kb)
    assert path == tmp_path / "results.json"
    assert (tmp_path / "RETRIEVAL_BENCH.md").exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["queries"]["total"] >= 40
    assert parsed["winner"] in {m["name"] for m in parsed["methods"]}
    for m in parsed["methods"]:
        assert {"hit@1", "hit@3", "hit@5", "mrr"} <= set(m)


def test_main_cli_exits_zero(kb, capsys, tmp_path, monkeypatch):
    # The CLI writes the same two artifacts: redirect before running it.
    monkeypatch.setattr(retrieval_bench, "RESULTS_PATH", tmp_path / "results.json")
    exit_code = retrieval_bench.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "hit@1" in out and "MRR" in out and "Winner" in out
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "RETRIEVAL_BENCH.md").exists()
