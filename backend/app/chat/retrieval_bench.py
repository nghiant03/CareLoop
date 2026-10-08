"""Retrieval method benchmark for the grounded chat pipeline.

Compares retrieval configurations over the same chunking used by
``backend/app/chat/retrieval.py`` (one chunk per current rule + one per dish,
built by the production ``KBIndex`` so the chunk contract is identical):

* ``bm25_word_syn``         — **the production index** (Okapi BM25 via
  ``rank_bm25`` over the production stopword-filtered word tokens + synonym
  expansion), wrapped as ``ProductionMethod``;
* ``bm25_word_nosyn``       — same scorer, raw query (no expansion);
* ``tfidf_word_asis_{syn,nosyn}`` — the *previous* production scorer (word
  TF-IDF; ``_syn`` was production until the BM25 switch) kept as a
  comparison row;
* ``tfidf_word_sublinear_{syn,nosyn}`` — ``sublinear_tf=True``;
* ``tfidf_char_wb_3_5_{syn,nosyn}`` — char_wb 3-5 gram TF-IDF.

Each method is scored on a labeled set of 58 queries (guideline/nutrient
questions mirroring ``evaluation/q_groundedness.py``, conflict questions,
dish/nutrient-content questions, and phrasing variants incl. typos) with
expected relevant chunk ids. Metrics: hit@1, hit@3, hit@5, MRR.

An end-to-end spot-check re-runs ~10 grounded questions through the real
``answers.answer`` composition with each retrieval method injected at runtime
(the ``retrieval.build_index`` module attribute is patched for the duration of
the call and restored afterwards — no source file is modified) and counts
citation accuracy (an cited ``rule_id`` matches the question's acceptable set).

Run: ``.venv/bin/python -m backend.app.chat.retrieval_bench``
Deterministic: fixed query order, deterministic vectorizers/tokenizers,
deterministic tie-breaking on ``chunk_id``, no timestamps in the artifacts.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.app.kb.graph_store import KBGraph, load_kb

__all__ = [
    "RESULTS_PATH", "PROD_NAME", "evaluate", "run_bench", "labeled_queries",
    "build_methods",
    "main",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "rules" / "rules.json"
DISHES_PATH = _REPO_ROOT / "data" / "dishes.json"
RESULTS_PATH = Path(__file__).resolve().parent / "retrieval_bench_results.json"

# Name of the production configuration row in the results (must match what
# ``backend/app/chat/retrieval.KBIndex`` actually runs — asserted in tests).
PROD_NAME = "bm25_word_syn"

# End-to-end spot-check: grounded questions (mix of nutrient questions with a
# constraint-producing anchor rule, plus sugar/fat questions where NO rule
# produces a constraint so citations must come from retrieval itself).
END_TO_END_QUESTIONS = [
    "How much sodium can I have per day?",
    "What is the sodium limit for someone with high blood pressure?",
    "How much potassium should I eat each day?",
    "How much potassium is safe if I have kidney disease?",
    "Do I need to worry about phosphorus in my diet?",
    "How much protein can I eat per day?",
    "How much fibre do I need daily?",
    "How many carbohydrates can I have per day?",
    "How much fat is okay in my diet?",
    "Can I drink sweet fizzy drinks?",
]


# ---------------------------------------------------------------------------
# Labeled query set
# ---------------------------------------------------------------------------

# Rule groups relevant per topic. "How much X" groups mirror the acceptable
# sets in evaluation/q_groundedness.py (rules that actually PRODUCE a
# constraint for the nutrient); topic groups are broader but still genuinely
# on-topic rule chunks.
_SODIUM = ["CKD-2024-SODIUM-2000", "CONFLICT-SODIUM-CKD-WINS",
           "DASH-2025-SODIUM-2300", "DASH-2025-SODIUM-1500",
           "ADA-2026-SODIUM-2300", "GEN-SODIUM-2300"]
_POTASSIUM = ["DASH-2025-POTASSIUM-4700", "HYPERK-2024-POTASSIUM-2400",
              "CONFLICT-K-DASH-VS-CKD", "SAFETY-HYPERK-SEVERE"]
_PROTEIN = ["CKD-2024-PROTEIN-055-08", "CKD-2024-PROTEIN-CEILING-13",
            "ADA-2026-PROTEIN"]
_ENERGY = ["CKD-2024-ENERGY-2535", "GEN-ENERGY-2535"]
_FIBER = ["DASH-2025-FIBER-30", "ADA-2026-FIBER-25-30", "GEN-FIBER-25"]
_SATFAT = ["DASH-2025-SATFAT-6PCT", "ADA-2026-SATFAT-10PCT"]
_CARB = ["ADA-2026-CARB-INDIV"]
_PHOS = ["HYPERPO4-2024-PHOSPHORUS-800", "CKD-2024-PHOSPHORUS-INDIV",
         "CKD-2024-PHOSPHATE-ADDITIVE", "HYPERPO4-2024-EXCLUDE-ADDITIVE",
         "HYPERPO4-2024-MONITOR"]
_SUGAR = ["ADA-2026-SUGAR-SSW", "GEN-SUGAR-10PCT"]
_FAT = ["GEN-FAT-2035", "DASH-2025-SATFAT-6PCT", "ADA-2026-SATFAT-10PCT"]
_WEIGHT = ["ADA-2026-WEIGHT-LOSS", "DASH-2025-WEIGHT-LOSS"]
_K_SALT_SUB = ["CKD-2024-NO-K-SALT-SUB", "HYPERK-2024-NO-SALT-SUB"]
_HYPERK = ["HYPERK-2024-POTASSIUM-2400", "HYPERK-2024-EXCLUDE-HIGH-K",
           "HYPERK-2024-NO-SALT-SUB", "HYPERK-2024-MONITOR",
           "SAFETY-HYPERK-SEVERE"]
_MED_K = ["MED-ACEI-ARB-K-CAUTION", "MED-ACEI-ARB-CKD-MONITOR",
          "MED-DIURETIC-K-LOSS"]
_CONFLICT_SODIUM = ["CONFLICT-SODIUM-CKD-WINS", "CKD-2024-SODIUM-2000"]
_CONFLICT_K = ["CONFLICT-K-DASH-VS-CKD", "CONFLICT-K-DASH-NORMAL"]


def _rules(*rule_ids: str) -> list[str]:
    return [f"rule:{rid}" for rid in rule_ids]


def _dishes_by_tag(kb: KBGraph, tag: str) -> list[str]:
    return [
        f"dish:{d['dish_id']}"
        for d in kb.dishes()
        if tag in (d.get("tags") or [])
    ]


def labeled_queries(kb: KBGraph) -> list[dict[str, Any]]:
    """The deterministic labeled retrieval set (58 queries).

    Each entry: ``id``, ``category``, ``query``, ``relevant`` (chunk ids) and
    an optional human ``note``. Order is fixed; relevance sets are derived
    from KB semantics (constraint-producing rules / dish tags), not from any
    retrieval method's behaviour.
    """
    R = _rules
    queries: list[dict[str, Any]] = [
        # -- guideline / nutrient questions (mirror evaluation/q_groundedness)
        {"id": "g01", "category": "guideline_nutrient", "query": "How much sodium can I have per day?", "relevant": R(*_SODIUM)},
        {"id": "g02", "category": "guideline_nutrient", "query": "Is salt bad for my blood pressure?", "relevant": R(*_SODIUM)},
        {"id": "g03", "category": "guideline_nutrient", "query": "What is the sodium limit for someone with high blood pressure?", "relevant": R(*_SODIUM)},
        {"id": "g04", "category": "guideline_nutrient", "query": "Why do I need to limit sodium?", "relevant": R(*_SODIUM)},
        {"id": "g05", "category": "guideline_nutrient", "query": "How much potassium should I eat each day?", "relevant": R(*_POTASSIUM)},
        {"id": "g06", "category": "guideline_nutrient", "query": "How much potassium is safe if I have kidney disease?", "relevant": R(*_POTASSIUM)},
        {"id": "g07", "category": "guideline_nutrient", "query": "Do I need to worry about phosphorus in my diet?", "relevant": R(*_PHOS)},
        {"id": "g08", "category": "guideline_nutrient", "query": "Are there foods I should avoid with phosphate additives?", "relevant": R(*_PHOS)},
        {"id": "g09", "category": "guideline_nutrient", "query": "How much protein can I eat per day?", "relevant": R(*_PROTEIN)},
        {"id": "g10", "category": "guideline_nutrient", "query": "Should I eat more protein?", "relevant": R(*_PROTEIN)},
        {"id": "g11", "category": "guideline_nutrient", "query": "How many calories should I eat per day?", "relevant": R(*_ENERGY)},
        {"id": "g12", "category": "guideline_nutrient", "query": "What is my calorie target?", "relevant": R(*_ENERGY)},
        {"id": "g13", "category": "guideline_nutrient", "query": "How much fibre do I need daily?", "relevant": R(*_FIBER)},
        {"id": "g14", "category": "guideline_nutrient", "query": "How much fiber should I aim for?", "relevant": R(*_FIBER)},
        {"id": "g15", "category": "guideline_nutrient", "query": "What about saturated fat - how much is too much?", "relevant": R(*_SATFAT)},
        {"id": "g16", "category": "guideline_nutrient", "query": "How many carbohydrates can I have per day?", "relevant": R(*_CARB)},
        {"id": "g17", "category": "guideline_nutrient", "query": "daily sodium ceiling for ckd patients", "relevant": R(*_CONFLICT_SODIUM)},
        {"id": "g18", "category": "guideline_nutrient", "query": "at least how much protein should I eat daily", "relevant": R(*_PROTEIN)},
        {"id": "g19", "category": "guideline_nutrient", "query": "low sodium eating tips", "relevant": R(*_SODIUM)},
        {"id": "g20", "category": "guideline_nutrient", "query": "potassium rich foods guidance", "relevant": R(*_POTASSIUM)},
        # -- conflict questions
        {"id": "c01", "category": "conflict", "query": "My kidney guideline says 2000 mg sodium but the hypertension guideline says 2300 mg - which applies?", "relevant": R(*_CONFLICT_SODIUM)},
        {"id": "c02", "category": "conflict", "query": "One guideline tells me to eat more potassium, another says limit potassium - what do I follow?", "relevant": R(*_CONFLICT_K)},
        {"id": "c03", "category": "conflict", "query": "Why do the sodium limits differ between the DASH and kidney guidelines?", "relevant": R("CONFLICT-SODIUM-CKD-WINS", "CKD-2024-SODIUM-2000", "DASH-2025-SODIUM-2300", "DASH-2025-SODIUM-1500")},
        {"id": "c04", "category": "conflict", "query": "Which rule wins when two guidelines disagree about potassium?", "relevant": R(*_CONFLICT_K)},
        {"id": "c05", "category": "conflict", "query": "conflicting advice about salt intake for kidney disease", "relevant": R(*_CONFLICT_SODIUM)},
        # -- phrasing variants incl. typos
        {"id": "t01", "category": "variant_typo", "query": "how much soduim per day", "relevant": R(*_SODIUM), "note": "typo: sodium"},
        {"id": "t02", "category": "variant_typo", "query": "wat is my daily salt limit", "relevant": R(*_SODIUM), "note": "typo: what"},
        {"id": "t03", "category": "variant_typo", "query": "protien intake advice for ckd", "relevant": R("CKD-2024-PROTEIN-055-08", "CKD-2024-PROTEIN-CEILING-13"), "note": "typo: protein"},
        {"id": "t04", "category": "variant_typo", "query": "how many calries a day", "relevant": R(*_ENERGY), "note": "typo: calories"},
        {"id": "t05", "category": "variant_typo", "query": "fibree recommandations", "relevant": R(*_FIBER), "note": "typos: fibre, recommendations"},
        {"id": "t06", "category": "variant_typo", "query": "potasium limit", "relevant": R(*_POTASSIUM), "note": "typo: potassium"},
        {"id": "t07", "category": "variant_typo", "query": "phospherus in my diet", "relevant": R(*_PHOS), "note": "typo: phosphorus"},
        {"id": "t08", "category": "variant_typo", "query": "can i drink sweet fizzy drinks", "relevant": R(*_SUGAR), "note": "plain phrasing for sugar rules"},
        # -- topical / non-constraint rules
        {"id": "p01", "category": "topic", "query": "can i use salt substitute", "relevant": R(*_K_SALT_SUB)},
        {"id": "p02", "category": "topic", "query": "is potassium based salt replacer safe for me", "relevant": R(*_K_SALT_SUB)},
        {"id": "p03", "category": "topic", "query": "can i drink alcohol with high blood pressure", "relevant": R("DASH-2025-ALCOHOL")},
        {"id": "p04", "category": "topic", "query": "should i try to lose weight", "relevant": R(*_WEIGHT)},
        {"id": "p05", "category": "topic", "query": "how much fat is okay in my diet", "relevant": R(*_FAT)},
        {"id": "p06", "category": "topic", "query": "does my blood pressure medicine change my potassium needs", "relevant": R(*_MED_K)},
        {"id": "p07", "category": "topic", "query": "water pill and low potassium", "relevant": R("MED-DIURETIC-K-LOSS")},
        {"id": "p08", "category": "topic", "query": "egfr and stages of kidney disease", "relevant": R("CKD-STAGE-CLASSIFY-EGFR")},
        {"id": "p09", "category": "topic", "query": "dangerously high potassium what should i eat", "relevant": R(*_HYPERK)},
        {"id": "p10", "category": "topic", "query": "sglt2 medicine and my diet", "relevant": R("MED-SGLT2I-CONTEXT")},
        {"id": "p11", "category": "topic", "query": "what does the dash dietary pattern recommend", "relevant": R("DASH-2025-MINERALS", "DASH-2025-FIBER-30", "DASH-2025-SATFAT-6PCT", "DASH-2025-SODIUM-2300", "DASH-2025-SODIUM-1500")},
        {"id": "p12", "category": "topic", "query": "metformin and diet advice", "relevant": R("MED-METFORMIN-CONTEXT")},
        # -- dish / nutrient-content questions
        {"id": "d01", "category": "dish", "query": "How much sodium is in Chicken Rice (Hainanese)?", "relevant": ["dish:SG0001"]},
        {"id": "d02", "category": "dish", "query": "sodium content of chicken rice", "relevant": ["dish:SG0001", "dish:SG0002"]},
        {"id": "d03", "category": "dish", "query": "how much soduim in chiken rice", "relevant": ["dish:SG0001", "dish:SG0002"], "note": "typos: sodium, chicken"},
        {"id": "d04", "category": "dish", "query": "is nasi lemak high in salt", "relevant": ["dish:SG0003", "dish:SG0004", "dish:SG0107"]},
        {"id": "d05", "category": "dish", "query": "how much sugar in a milo dinosaur", "relevant": ["dish:SG0174"]},
        {"id": "d06", "category": "dish", "query": "sugarcane juce sugar content", "relevant": ["dish:SG0177"], "note": "typo: juice"},
        {"id": "d07", "category": "dish", "query": "fibre in the mushroom corn oat porridge", "relevant": ["dish:SG0207"]},
        {"id": "d08", "category": "dish", "query": "steamed fish teochew style nutrition", "relevant": ["dish:SG0079"]},
        {"id": "d09", "category": "dish", "query": "calories in grilled salmon steak", "relevant": ["dish:SG0135"]},
        {"id": "d10", "category": "dish", "query": "which dishes are high in potassium", "relevant": _dishes_by_tag(kb, "high_potassium")},
        {"id": "d11", "category": "dish", "query": "i need more fibre which dishes can i eat", "relevant": _dishes_by_tag(kb, "high_fiber")},
        {"id": "d12", "category": "dish", "query": "vegetarian dish ideas", "relevant": _dishes_by_tag(kb, "vegetarian")},
        {"id": "d13", "category": "dish", "query": "fruit for a snack", "relevant": _dishes_by_tag(kb, "fruit")},
    ]
    for q in queries:
        q["relevant"] = sorted(set(q["relevant"]))
    return queries


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Production tokenizer (delegates to ``retrieval._tokenize``).

    Kept as a module symbol so the BM25 bench methods and production always
    tokenize identically — single source of truth lives in
    ``backend/app/chat/retrieval.py``.
    """
    from backend.app.chat import retrieval as production_retrieval

    return production_retrieval._tokenize(text)


class BenchMethod:
    """Common interface: ``retrieve(query, k) -> [{chunk_id, score}, ...]``."""

    name: str = "base"

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class ProductionMethod(BenchMethod):
    """The production ``retrieval.KBIndex`` exactly as configured today.

    Since the BM25 switch this is the ``bm25_word_syn`` configuration; the
    name is asserted to match ``PROD_NAME`` so the report can never silently
    drift from what production runs.
    """

    def __init__(self, index: Any, name: str) -> None:
        self.name = name
        self._index = index

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        # KBIndex hits are already full chunk dicts + score — pass through.
        return list(self._index.retrieve(query, k=k))


class TfidfMethod(BenchMethod):
    def __init__(
        self,
        name: str,
        chunks: list[dict[str, Any]],
        vectorizer: TfidfVectorizer,
        expand: Optional[Callable[[str], str]],
    ) -> None:
        self.name = name
        self._chunks = chunks
        self._ids = [c["chunk_id"] for c in chunks]
        self._expand = expand
        corpus = [c["text"] for c in chunks] or ["empty knowledge base"]
        self._vectorizer = vectorizer
        self._matrix = vectorizer.fit_transform(corpus)

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        text = self._expand(query) if self._expand else query
        vec = self._vectorizer.transform([text])
        scores = (vec @ self._matrix.T).toarray()[0]
        ranked = sorted(
            (
                (float(score), idx)
                for idx, score in enumerate(scores)
                if score > 0.0
            ),
            key=lambda pair: (-pair[0], self._ids[pair[1]]),
        )
        return [
            {**self._chunks[idx], "score": score}
            for score, idx in ranked[: max(k, 0)]
        ]


class BM25Method(BenchMethod):
    def __init__(
        self,
        name: str,
        chunks: list[dict[str, Any]],
        expand: Optional[Callable[[str], str]],
    ) -> None:
        self.name = name
        self._chunks = chunks
        self._ids = [c["chunk_id"] for c in chunks]
        self._expand = expand
        tokenized = [_tokenize(c["text"]) for c in chunks] or [["empty"]]
        self._bm25 = BM25Okapi(tokenized)

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        text = self._expand(query) if self._expand else query
        scores = self._bm25.get_scores(_tokenize(text))
        ranked = sorted(
            (
                (float(score), idx)
                for idx, score in enumerate(scores)
                if score > 0.0
            ),
            key=lambda pair: (-pair[0], self._ids[pair[1]]),
        )
        return [
            {**self._chunks[idx], "score": score}
            for score, idx in ranked[: max(k, 0)]
        ]


def build_methods(kb: KBGraph) -> dict[str, BenchMethod]:
    """Build every benchmark method over the production chunking.

    The production ``KBIndex`` (BM25 + synonym expansion) is wrapped as
    ``ProductionMethod`` under ``PROD_NAME``. The previous production scorer
    (word TF-IDF + expansion) is kept as the ``tfidf_word_asis_syn`` row for
    comparison; ``tfidf_word_asis_syn`` is no longer production.
    """
    # Imported here so importing this module never mutates module state.
    from backend.app.chat import retrieval as production_retrieval

    prod_index = production_retrieval.build_index(kb)
    chunks = prod_index.chunks
    expand: Callable[[str], str] = prod_index._expand_query

    def word_vectorizer(**kwargs: Any) -> TfidfVectorizer:
        return TfidfVectorizer(stop_words="english", **kwargs)

    methods: dict[str, BenchMethod] = {
        "tfidf_word_asis_syn": TfidfMethod(
            "tfidf_word_asis_syn", chunks, word_vectorizer(), expand
        ),
        "tfidf_word_asis_nosyn": TfidfMethod(
            "tfidf_word_asis_nosyn", chunks, word_vectorizer(), expand=None
        ),
        "tfidf_word_sublinear_syn": TfidfMethod(
            "tfidf_word_sublinear_syn", chunks, word_vectorizer(sublinear_tf=True), expand
        ),
        "tfidf_word_sublinear_nosyn": TfidfMethod(
            "tfidf_word_sublinear_nosyn", chunks, word_vectorizer(sublinear_tf=True), None
        ),
        "tfidf_char_wb_3_5_syn": TfidfMethod(
            "tfidf_char_wb_3_5_syn", chunks,
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1), expand,
        ),
        "tfidf_char_wb_3_5_nosyn": TfidfMethod(
            "tfidf_char_wb_3_5_nosyn", chunks,
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1), None,
        ),
        PROD_NAME: ProductionMethod(prod_index, PROD_NAME),
        "bm25_word_nosyn": BM25Method("bm25_word_nosyn", chunks, None),
    }
    return methods


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _query_metrics(ranked_ids: list[str], relevant: set[str]) -> dict[str, float]:
    hits = {
        f"hit@{k}": float(any(rid in relevant for rid in ranked_ids[:k]))
        for k in (1, 3, 5)
    }
    rr = 0.0
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            rr = 1.0 / rank
            break
    hits["mrr"] = rr
    return hits


def _aggregate(per_query: list[dict[str, float]]) -> dict[str, float]:
    if not per_query:
        return {key: 0.0 for key in ("hit@1", "hit@3", "hit@5", "mrr")}
    n = len(per_query)
    return {
        key: sum(row[key] for row in per_query) / n
        for key in ("hit@1", "hit@3", "hit@5", "mrr")
    }


def _rank_retrieval_methods(results: list[dict[str, Any]]) -> list[str]:
    return [
        m["name"]
        for m in sorted(
            results,
            key=lambda m: (-round(m["mrr"], 6), -round(m["hit@5"], 6),
                           -round(m["hit@1"], 6), m["name"]),
        )
    ]


def _answer_with_method(method: BenchMethod, kb: KBGraph, question: str) -> dict[str, Any]:
    """Run the real ``answers.answer`` with ``method`` injected for retrieval.

    Patches the ``backend.app.chat.retrieval.build_index`` module attribute for
    the duration of one call and restores it afterwards — no source file is
    modified.
    """
    from backend.app.chat import retrieval as retrieval_module
    from backend.app.chat.answers import answer

    original = retrieval_module.build_index
    retrieval_module.build_index = lambda kb_: method
    try:
        return answer(question, kb, envelope=None, role="patient")
    finally:
        retrieval_module.build_index = original


def _norm_question(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()


def _end_to_end_spot_check(
    methods: dict[str, BenchMethod],
    kb: KBGraph,
    relevant_by_question: dict[str, set[str]],
) -> dict[str, Any]:
    from backend.app.chat import escalation

    rows_out: dict[str, list[dict[str, Any]]] = {}
    for name, method in methods.items():
        rows = []
        for question in END_TO_END_QUESTIONS:
            if escalation.check(question)["escalate"]:
                continue  # never expected for these grounded questions
            response = _answer_with_method(method, kb, question)
            cited = [c.get("rule_id") for c in response.get("citations", [])]
            acceptable = {
                cid.split(":", 1)[1]
                for cid in relevant_by_question.get(_norm_question(question), set())
                if cid.startswith("rule:")
            }
            rows.append({
                "question": question,
                "status": response["status"],
                "cited_rule_ids": cited,
                "citation_accurate": bool(cited)
                and any(rid in acceptable for rid in cited),
            })
        rows_out[name] = rows
    return {
        "questions": END_TO_END_QUESTIONS,
        "methods": {
            name: {
                "citation_accuracy": (
                    sum(1 for r in rows if r["citation_accurate"]) / len(rows)
                    if rows else 0.0
                ),
                "answered": sum(1 for r in rows if r["status"] == "answered"),
                "rows": rows,
            }
            for name, rows in rows_out.items()
        },
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(kb: Optional[KBGraph] = None) -> dict[str, Any]:
    """Run the full benchmark and return the results dict (deterministic)."""
    if kb is None:
        kb = load_kb(RULES_PATH, DISHES_PATH)

    methods = build_methods(kb)
    queries = labeled_queries(kb)
    chunks = methods[PROD_NAME]._index.chunks  # production chunking
    all_chunk_ids = {c["chunk_id"] for c in chunks}

    method_results: list[dict[str, Any]] = []
    for name, method in methods.items():
        per_query = []
        by_category: dict[str, list[dict[str, float]]] = {}
        for q in queries:
            ranked = [hit["chunk_id"] for hit in method.retrieve(q["query"], k=5)]
            metrics = _query_metrics(ranked, set(q["relevant"]))
            per_query.append(metrics)
            by_category.setdefault(q["category"], []).append(metrics)
        row = {
            "name": name,
            **{k: round(v, 4) for k, v in _aggregate(per_query).items()},
            "by_category": {
                cat: {k: round(v, 4) for k, v in _aggregate(rows).items()}
                for cat, rows in sorted(by_category.items())
            },
        }
        method_results.append(row)

    ranked_names = _rank_retrieval_methods(method_results)

    relevant_by_question = {
        _norm_question(q["query"]): set(q["relevant"]) for q in queries
    }
    e2e = _end_to_end_spot_check(methods, kb, relevant_by_question)
    e2e_summary = {
        name: {
            "citation_accuracy": round(stats["citation_accuracy"], 4),
            "answered": stats["answered"],
        }
        for name, stats in e2e["methods"].items()
    }

    return {
        "kb": {
            "rules": len(kb.rules()),
            "dishes": len(kb.dishes()),
            "chunks": len(chunks),
            "distinct_chunk_ids": len(all_chunk_ids),
        },
        "queries": {
            "total": len(queries),
            "by_category": {
                cat: sum(1 for q in queries if q["category"] == cat)
                for cat in sorted({q["category"] for q in queries})
            },
        },
        "methods": method_results,
        "ranking": ranked_names,
        "winner": ranked_names[0],
        "end_to_end": {"summary": e2e_summary, "detail": e2e},
    }


def write_results(results: dict[str, Any], path: Optional[Path] = None) -> Path:
    """Write the results artifact (sorted keys, rounded floats => deterministic)."""
    target = Path(path) if path is not None else RESULTS_PATH
    target.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def run_bench(kb: Optional[KBGraph] = None) -> tuple[dict[str, Any], Path]:
    """Evaluate + write the artifact; returns (results, artifact_path)."""
    results = evaluate(kb)
    return results, write_results(results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt(value: float) -> str:
    return f"{value:.2f}"


def main(argv: Optional[list[str]] = None) -> int:
    results, artifact = run_bench()

    print(f"KB: {results['kb']['rules']} rules, {results['kb']['dishes']} dishes "
          f"-> {results['kb']['chunks']} chunks")
    print(f"Labeled queries: {results['queries']['total']} "
          f"{results['queries']['by_category']}")
    print()
    header = f"{'method':<28}{'hit@1':>7}{'hit@3':>7}{'hit@5':>7}{'MRR':>7}"
    print(header)
    print("-" * len(header))
    for row in results["methods"]:
        print(
            f"{row['name']:<28}{_fmt(row['hit@1']):>7}{_fmt(row['hit@3']):>7}"
            f"{_fmt(row['hit@5']):>7}{_fmt(row['mrr']):>7}"
        )
    print()
    print(f"Winner (MRR, deterministic tie-break): {results['winner']}")
    print()
    print("End-to-end citation accuracy (answers.answer spot-check, "
          f"{len(END_TO_END_QUESTIONS)} grounded questions):")
    for name in results["ranking"]:
        stats = results["end_to_end"]["summary"][name]
        print(f"  {name:<28} citation_accuracy={stats['citation_accuracy']:.2f} "
              f"answered={stats['answered']}")
    print(f"\nArtifact written: {artifact}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())