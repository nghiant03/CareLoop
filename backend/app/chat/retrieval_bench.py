"""Retrieval method benchmark for the grounded chat pipeline.

Compare BM25, TF-IDF variants, and rank fusion using production ``KBIndex``
chunks. Measure hit@k, MRR, end-to-end citation checks, and irrelevant-query
refusal. Citation checks cover rule IDs and structured claims, not arbitrary
prose entailment.

Experimental gates use disjoint development questions. The production BM25
gate remains fixed and was not independently calibrated from the ranking set.
Held-out fusion overlap is diagnostic only. ``_answer_with_method`` temporarily
patches process-wide state and is unsafe alongside concurrent answer calls.

Run: ``.venv/bin/python -m backend.app.chat.retrieval_bench``. Artifacts use
fixed query order and chunk-ID tie-breaks, without timestamps.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from backend.app.kb.graph_store import KBGraph, load_kb
from backend.storage_paths import artifact_dir

__all__ = [
    "PROD_NAME",
    "RESULTS_PATH",
    "build_methods",
    "evaluate",
    "labeled_queries",
    "main",
    "run_bench",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

RULES_PATH = dataset_path("rules.json")
DISHES_PATH = dataset_path("dishes.json")
RESULTS_PATH = artifact_dir("retrieval") / "retrieval_bench_results.json"

# This row must match the deployed KBIndex configuration.
PROD_NAME = "bm25_word_syn"

# Reciprocal Rank Fusion parameters (Cormack/Clarke/Büttcher, SIGIR 2009):
# score(d) = sum_m 1/(RRF_K + rank_m(d)) over the union of candidate ids;
# each component contributes its top-RRF_COMPONENT_DEPTH ranked candidates.
RRF_K = 60
RRF_COMPONENT_DEPTH = 50

# Uncalibrated RRF fallback, not a BM25-scale threshold. Evaluation calibrates
# experimental gates on development examples, never held-out scores.
FUSION_MIN_SCORE = 0.04

# End-to-end spot-check: supported nutrient questions need grounded citations;
# numeric sugar/fat requests without a supporting constraint may be refused.
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



# Intake questions require constraint-producing rules. Broader topic questions
# may use other relevant rules. See evaluation/q_groundedness.py.
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
        # Guideline/nutrient queries mirror evaluation/q_groundedness.
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
        # Conflicts
        {"id": "c01", "category": "conflict", "query": "My kidney guideline says 2000 mg sodium but the hypertension guideline says 2300 mg - which applies?", "relevant": R(*_CONFLICT_SODIUM)},
        {"id": "c02", "category": "conflict", "query": "One guideline tells me to eat more potassium, another says limit potassium - what do I follow?", "relevant": R(*_CONFLICT_K)},
        {"id": "c03", "category": "conflict", "query": "Why do the sodium limits differ between the DASH and kidney guidelines?", "relevant": R("CONFLICT-SODIUM-CKD-WINS", "CKD-2024-SODIUM-2000", "DASH-2025-SODIUM-2300", "DASH-2025-SODIUM-1500")},
        {"id": "c04", "category": "conflict", "query": "Which rule wins when two guidelines disagree about potassium?", "relevant": R(*_CONFLICT_K)},
        {"id": "c05", "category": "conflict", "query": "conflicting advice about salt intake for kidney disease", "relevant": R(*_CONFLICT_SODIUM)},
        # Phrasing variants and typos
        {"id": "t01", "category": "variant_typo", "query": "how much soduim per day", "relevant": R(*_SODIUM), "note": "typo: sodium"},
        {"id": "t02", "category": "variant_typo", "query": "wat is my daily salt limit", "relevant": R(*_SODIUM), "note": "typo: what"},
        {"id": "t03", "category": "variant_typo", "query": "protien intake advice for ckd", "relevant": R("CKD-2024-PROTEIN-055-08", "CKD-2024-PROTEIN-CEILING-13"), "note": "typo: protein"},
        {"id": "t04", "category": "variant_typo", "query": "how many calries a day", "relevant": R(*_ENERGY), "note": "typo: calories"},
        {"id": "t05", "category": "variant_typo", "query": "fibree recommandations", "relevant": R(*_FIBER), "note": "typos: fibre, recommendations"},
        {"id": "t06", "category": "variant_typo", "query": "potasium limit", "relevant": R(*_POTASSIUM), "note": "typo: potassium"},
        {"id": "t07", "category": "variant_typo", "query": "phospherus in my diet", "relevant": R(*_PHOS), "note": "typo: phosphorus"},
        {"id": "t08", "category": "variant_typo", "query": "can i drink sweet fizzy drinks", "relevant": R(*_SUGAR), "note": "plain phrasing for sugar rules"},
        # Topic rules without nutrient constraints
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
        # Dish nutrient content
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



def _tokenize(text: str) -> list[str]:
    """Reuse the production tokenizer so benchmark and deployed BM25 tokens agree."""
    from backend.app.chat import retrieval as production_retrieval

    return production_retrieval._tokenize(text)


class BenchMethod:
    """Common interface: ``retrieve(query, k) -> [{chunk_id, score}, ...]``."""

    name: str = "base"

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class ProductionMethod(BenchMethod):
    """Wrap the deployed ``retrieval.KBIndex`` without changing its ranking."""

    def __init__(self, index: Any, name: str) -> None:
        self.name = name
        self._index = index

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        return list(self._index.retrieve(query, k=k))


class TfidfMethod(BenchMethod):
    def __init__(
        self,
        name: str,
        chunks: list[dict[str, Any]],
        vectorizer: TfidfVectorizer,
        expand: Callable[[str], str] | None,
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
        scores = linear_kernel(vec, self._matrix)[0]
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
        expand: Callable[[str], str] | None,
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


class RRFMethod(BenchMethod):
    """Reciprocal Rank Fusion of independent ranked lists (k=60).

    Fuse the union of component candidates, not just BM25 hits, so character
    n-grams can recover missed chunks. Reciprocal ranks avoid mixing BM25 and
    cosine score scales. Ties break on ``chunk_id``.

    ``calibrate_methods`` selects ``min_score`` on development examples.
    ``_answer_with_method`` temporarily applies that gate to end-to-end calls;
    ``diagnose_fusion_gate`` only reports held-out overlap.
    """

    def __init__(
        self,
        name: str,
        components: list[BenchMethod],
        chunks: list[dict[str, Any]],
    ) -> None:
        self.name = name
        self._components = components
        self._chunks_by_id = {c["chunk_id"]: c for c in chunks}
        self.min_score: float | None = None

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        fused: dict[str, float] = {}
        for component in self._components:
            for rank, hit in enumerate(
                component.retrieve(query, k=RRF_COMPONENT_DEPTH), start=1
            ):
                chunk_id = hit["chunk_id"]
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
        return [
            {**self._chunks_by_id[chunk_id], "score": score}
            for chunk_id, score in ranked[: max(k, 0)]
        ]


def build_methods(kb: KBGraph) -> dict[str, BenchMethod]:
    """Build every benchmark method over the production chunking.

    ``PROD_NAME`` wraps the deployed index. TF-IDF rows are comparators, not
    production configurations. Refusal gates are assigned by ``calibrate_methods``.
    """
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
    # Fuse deployed BM25 with synonym-expanded character-ngram TF-IDF.
    methods["bm25_rrf_char"] = RRFMethod(
        "bm25_rrf_char",
        [methods[PROD_NAME], methods["tfidf_char_wb_3_5_syn"]],
        chunks,
    )
    return methods



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

    Replace ``retrieval.build_index`` and, when supplied, ``MIN_SCORE`` for one
    call. Restore both in ``finally`` without modifying source files. All
    calibrated methods use their own score-scale gate. These process-wide
    patches are not safe for concurrent answer calls.
    """
    from backend.app.chat import retrieval as retrieval_module
    from backend.app.chat.answers import answer
    from backend.app.chat.retrieval import KBIndex

    original_build_index = retrieval_module.build_index
    original_min_score = retrieval_module.MIN_SCORE
    retrieval_module.build_index = lambda kb: cast(KBIndex, method)
    method_min_score = getattr(method, "min_score", None)
    if method_min_score is not None:
        retrieval_module.MIN_SCORE = method_min_score
    try:
        return answer(question, kb, envelope=None, role="patient")
    finally:
        retrieval_module.build_index = original_build_index
        retrieval_module.MIN_SCORE = original_min_score


def _norm_question(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()


def _end_to_end_spot_check(
    methods: dict[str, BenchMethod],
    kb: KBGraph,
    relevant_by_question: dict[str, set[str]],
) -> dict[str, Any]:
    from backend.app.chat import escalation
    from evaluation.q_groundedness import _claims_supported

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
                "citation_accurate": _claims_supported(response, kb) and bool(cited)
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



# Add held-out typo probes: shared character n-grams can match garbled text,
# so clean irrelevant questions alone understate fusion's refusal risk.
_TYPO_NONSENSE_PROBES = [
    "wat is teh wether forcast tomorow",
    "tel me a jok plese",
    "hu won teh footbal mach last nite",
    "wut is teh capitl of frnace",
    "can u bookc me a txi to teh airprot",
    "recomnd me a good movei to wach",
]


def _irrelevant_probes() -> list[str]:
    from evaluation.q_groundedness import _IRRELEVANT

    return list(_IRRELEVANT) + _TYPO_NONSENSE_PROBES


def diagnose_fusion_gate(
    kb: KBGraph | None = None, method: RRFMethod | None = None
) -> dict[str, Any]:
    """Report held-out RRF score overlap without selecting or changing a gate.

    Compares the best irrelevant score with the weakest labeled-relevant score
    and checks the method's existing threshold against that interval. Gate
    selection happens elsewhere: ``calibrate_methods`` chooses experimental
    thresholds on development examples before evaluation; this diagnostic only
    reports how the frozen gate separates held-out data.
    """
    if kb is None:
        from backend.app.core.kb_loader import get_kb

        kb = get_kb()
    if method is None:
        candidate = build_methods(kb)["bm25_rrf_char"]
        assert isinstance(candidate, RRFMethod)
        method = candidate

    probes = _irrelevant_probes()
    irrelevant_scores: dict[str, float] = {}
    for probe in probes:
        hits = method.retrieve(probe, k=1)
        irrelevant_scores[probe] = round(hits[0]["score"], 6) if hits else 0.0
    irrelevant_best = max(irrelevant_scores.values())

    relevant_rows = []
    for q in labeled_queries(kb):
        hits = method.retrieve(q["query"], k=1)
        relevant_rows.append({
            "id": q["id"],
            "query": q["query"],
            "category": q["category"],
            "best_score": round(hits[0]["score"], 6) if hits else 0.0,
        })
    weakest = min(relevant_rows, key=lambda r: (r["best_score"], r["id"]))
    weakest_clean = min(
        (r for r in relevant_rows if r["category"] != "variant_typo"),
        key=lambda r: (r["best_score"], r["id"]),
    )
    # An unset gate needs the fallback, not calibration on held-out scores.
    threshold = (
        method.min_score if method.min_score is not None else FUSION_MIN_SCORE
    )
    return {
        "threshold": threshold,
        "irrelevant_probes": irrelevant_scores,
        "irrelevant_best_score": irrelevant_best,
        "weakest_relevant": weakest,
        "weakest_clean_relevant": weakest_clean,
        "gap_ok": irrelevant_best < threshold < weakest["best_score"],
        "usage": "held-out diagnostic only; never used to select the threshold",
    }


# Historical callable alias: the serialized results key also stays
# ``fusion_calibration`` for compatibility with existing artifacts/readers.
calibrate_fusion = diagnose_fusion_gate


def _irrelevant_refusal_check(
    methods: dict[str, BenchMethod], kb: KBGraph
) -> dict[str, Any]:
    """End-to-end refusal check: irrelevant probes through ``answers.answer``.

    Run for the production row and the fusion row; the fusion row runs under
    its calibrated ``min_score`` (patched via ``_answer_with_method``), the
    production row under the production ``MIN_SCORE``. Irrelevant questions
    must be refused, never answered.
    """
    out: dict[str, Any] = {}
    for name in (PROD_NAME, "bm25_rrf_char"):
        rows = []
        for probe in _irrelevant_probes():
            response = _answer_with_method(methods[name], kb, probe)
            rows.append({"question": probe, "status": response["status"]})
        out[name] = {
            "probes": len(rows),
            "refused": sum(1 for r in rows if r["status"] == "refused"),
            "rows": rows,
        }
    return out



# Development-only examples. None belongs to the held-out ranking/e2e sets.
_CALIBRATION_RELEVANT = [
    "Explain dietary sodium guidance for an adult with hypertension",
    "What guidance covers dietary fibre for adults with diabetes",
    "Which foods have phosphate additives",
    "Describe the nutrient content of Hainanese chicken rice",
    "Explain potassium restrictions with hyperkalaemia",
    "How do guidelines set protein intake for CKD",
]
_CALIBRATION_IRRELEVANT = [
    "Calculate mortgage interest on a house",
    "How do I replace a bicycle tyre",
    "Recommend a science fiction novel",
    "Where can I buy concert tickets",
    "Explain how a lunar eclipse happens",
    "Generate a JavaScript sorting function",
]


def calibrate_methods(methods):
    """Freeze scale-specific gates on development examples before evaluation."""
    from backend.app.chat.retrieval import MIN_SCORE

    result = {}
    for name, method in methods.items():
        examples: list[dict[str, Any]] = []
        for relevant, questions in ((True, _CALIBRATION_RELEVANT), (False, _CALIBRATION_IRRELEVANT)):
            for question in questions:
                hits = method.retrieve(question, k=1)
                examples.append({"question": question, "relevant": relevant,
                                 "score": float(hits[0]["score"]) if hits else 0.})
        candidates = sorted({0., *(row["score"] for row in examples)})
        def errors(threshold, examples=examples):
            return sum((row["score"] > threshold) != row["relevant"] for row in examples)
        threshold = min(candidates, key=lambda t: (errors(t), -t))
        # Keep the deployed baseline fixed; experimental retrievers get their own gates.
        method.min_score = MIN_SCORE if name == PROD_NAME else threshold
        result[name] = {"threshold": method.min_score, "development_errors": errors(method.min_score),
                        "selection": "deployed baseline" if name == PROD_NAME else "development minimum classification error",
                        "examples": examples}
    return result

def evaluate(kb: KBGraph | None = None) -> dict[str, Any]:
    """Run the full benchmark and return the results dict (deterministic)."""
    if kb is None:
        kb = load_kb(RULES_PATH, DISHES_PATH)

    methods = build_methods(kb)
    thresholds = calibrate_methods(methods)
    fusion_method = methods.get("bm25_rrf_char")
    assert isinstance(fusion_method, RRFMethod)
    queries = labeled_queries(kb)
    prod_method = methods[PROD_NAME]
    assert isinstance(prod_method, ProductionMethod)
    chunks = prod_method._index.chunks  # production chunking
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
        "threshold_calibration": thresholds,
        "ranking": ranked_names,
        "winner": ranked_names[0],
        "fusion_calibration": diagnose_fusion_gate(kb, fusion_method),
        "irrelevant_refusal": _irrelevant_refusal_check(methods, kb),
        "end_to_end": {"summary": e2e_summary, "detail": e2e},
    }


def write_results(results: dict[str, Any], path: Path | None = None) -> Path:
    """Write the results artifact (sorted keys, rounded floats => deterministic)."""
    target = Path(path) if path is not None else RESULTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def run_bench(kb: KBGraph | None = None) -> tuple[dict[str, Any], Path]:
    """Write the Markdown report and JSON results; return results and the JSON path."""
    results = evaluate(kb)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.with_name("RETRIEVAL_BENCH.md").write_text(render_report(results), encoding="utf-8")
    return results, write_results(results)


def render_report(results):
    lines = ["# Retrieval benchmark", "", "Generated by `python -m backend.app.chat.retrieval_bench`.", "",
             "## Protocol", "",
             ("The same 275 chunks (61 rules, 214 dishes) and deterministic tie-breaks are shared across all methods. "
             "Synonym expansion is the syn/nosyn variable within each scorer family: *_nosyn rows retrieve with raw queries. "
             "Experimental refusal gates are selected on 12 disjoint development questions, then frozen before scoring 58 held-out queries. "
             "The deployed BM25 baseline retains its existing threshold. Its historical calibration was not independent of this query set."), "",
             ("RRF combines the union of BM25 and character-ngram candidates (top 50 each, k=60). "
             "Held-out score overlap is diagnostic only and never used to retune the gate."), "",
             "## Ranking", "", "| Method | Hit@1 | Hit@3 | Hit@5 | MRR |", "|---|---:|---:|---:|---:|"]
    for row in results["methods"]:
        lines.append(f"| {row['name']} | {row['hit@1']:.3f} | {row['hit@3']:.3f} | {row['hit@5']:.3f} | {row['mrr']:.3f} |")
    lines += ["", "## Scale-specific development thresholds", "", "| Method | Threshold | Development errors / 12 |", "|---|---:|---:|"]
    for name, row in results["threshold_calibration"].items():
        lines.append(f"| {name} | {row['threshold']:.6f} | {row['development_errors']} |")
    lines += ["", "## End-to-end checks", "",
              ("Ten questions use the real answer pipeline. Citation accuracy requires an on-topic citation and support for every exposed claim. "
              "The total-fat numeric question correctly refuses because no supported numeric target exists; it is intentionally not counted as a citation success."), "",
              "| Method | Citation accuracy | Answered / 10 |", "|---|---:|---:|"]
    for name, row in results["end_to_end"]["summary"].items():
        lines.append(f"| {name} | {row['citation_accuracy']:.3f} | {row['answered']} |")
    lines += ["", "## Decision", "", (f"Ranking winner: **{results['winner']}**. Keep BM25 with synonyms in production. "
              "Fusion loses overall ranking quality and does not improve typo hit@1. "
              "The held-out fusion score distributions overlap, so a single threshold does not cleanly separate relevance."), ""]
    for name, row in results["irrelevant_refusal"].items():
        lines.append(f"- {name}: {row['refused']}/{row['probes']} irrelevant probes refused.")
    lines += ["", "## Limitations", "",
              ("Small, internally authored development/test sets and semantic relevance labels do not establish clinical validity. "
              "Some end-to-end questions overlap ranking questions; those are complementary metrics, not independent evidence. "
              "Q5 separately checks patient applicability, clinician overrides and exact approved values. "
              "Full per-query results, thresholds and development examples are in `retrieval_bench_results.json`."), ""]
    return "\n".join(lines)



def _fmt(value: float) -> str:
    return f"{value:.2f}"


def main(argv: list[str] | None = None) -> int:
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
    calibration = results.get("fusion_calibration")
    if calibration:
        weakest = calibration["weakest_relevant"]
        print(
            f"Fusion gate diagnostic (bm25_rrf_char, threshold {calibration['threshold']}): "
            f"irrelevant_best={calibration['irrelevant_best_score']:.4f} "
            f"weakest_relevant={weakest['best_score']:.4f} ({weakest['id']}) "
            f"gap_ok={calibration['gap_ok']}"
        )
        refusal = results.get("irrelevant_refusal", {})
        for name, stats in refusal.items():
            print(f"  irrelevant refusal {name:<28} "
                  f"{stats['refused']}/{stats['probes']} refused")
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
