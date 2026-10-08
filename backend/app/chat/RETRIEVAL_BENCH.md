# Retrieval Method Benchmark — Grounded Chat Pipeline

**Decision recorded:** the production default in `backend/app/chat/retrieval.py`
is now `bm25_word_syn` (Okapi BM25 + synonym expansion over the unchanged
production chunking). This report documents the benchmark behind that switch
and the accompanying `MIN_SCORE` recalibration.

- Benchmark module: `backend/app/chat/retrieval_bench.py`
  (run: `.venv/bin/python -m backend.app.chat.retrieval_bench`)
- Machine-readable artifact: `backend/app/chat/retrieval_bench_results.json`
- Tests: `backend/app/tests/test_retrieval_bench.py`

## Setup

- **Chunking**: identical to production — one chunk per current rule + one per
  dish (275 chunks: 61 rules, 214 dishes), built by the production `KBIndex`
  itself so the chunk text, synonyms and chunk ids are exactly what ships.
- **BM25 tokenization**: shared with production
  (`retrieval._tokenize` — word tokens minus English stopwords). The
  stopword filter matches the previous TF-IDF config
  (`stop_words="english"`) and is required for the refusal gate (see
  *MIN_SCORE calibration* below).
- **Labeled set**: 58 queries in 5 categories
  (`guideline_nutrient` 20, `topic` 12, `dish` 13, `conflict` 5,
  `variant_typo` 8). Guideline questions mirror
  `evaluation/q_groundedness.py`; relevance sets derive from KB semantics
  (rules that actually produce a constraint for the nutrient, dish tags,
  conflict-policy rules) — not from any method's behaviour.
- **Metrics**: hit@1 / hit@3 / hit@5, MRR over each query's relevant chunk-id
  set; deterministic tie-break on `chunk_id`.
- **End-to-end spot-check**: the real `answers.answer` pipeline with each
  method injected at runtime (the `retrieval.build_index` module attribute is
  patched for the duration of one call and restored — no source file is
  modified) over 10 grounded questions; citation accuracy = answered with ≥1
  cited `rule_id` in the question's acceptable set. The set deliberately
  includes sugar/fat questions where **no rule produces a constraint**, so the
  anchor-rule path is unavailable and citations must come from retrieval.
  All rows run under the **production** `MIN_SCORE` gate; that gate is
  calibrated for BM25 score scale, so the TF-IDF rows (cosine ≤ 1.0) have
  their retrieval-only questions refused — those rows' e2e numbers are
  indicative only, the production row is the one that ships.

## Headline results (58 queries)

| method                       | hit@1 | hit@3 | hit@5 |  MRR |
|------------------------------|------:|------:|------:|-----:|
| **bm25_word_syn (prod)**     | **0.638** | **0.776** | 0.793 | **0.706** |
| tfidf_char_wb_3_5_syn        | 0.603 | 0.741 | 0.759 | 0.671 |
| bm25_word_nosyn              | 0.569 | 0.741 | **0.810** | 0.659 |
| tfidf_word_asis_syn (prev)   | 0.517 | 0.672 | 0.741 | 0.601 |
| tfidf_char_wb_3_5_nosyn      | 0.448 | 0.707 | 0.810 | 0.587 |
| tfidf_word_sublinear_syn     | 0.448 | 0.621 | 0.672 | 0.544 |
| tfidf_word_asis_nosyn        | 0.431 | 0.621 | 0.724 | 0.536 |
| tfidf_word_sublinear_nosyn   | 0.362 | 0.603 | 0.690 | 0.488 |

## Per-category breakdown (MRR unless noted)

| method                       | guideline | dish  | conflict | topic | typo hit@1 |
|------------------------------|----------:|------:|---------:|------:|-----------:|
| **bm25_word_syn (prod)**     | **0.88**  | 0.85  | **0.67** | 0.49  | 0.38       |
| tfidf_char_wb_3_5_syn        | 0.74      | **0.88** | 0.30  | 0.57  | **0.50**   |
| bm25_word_nosyn              | 0.64      | 0.85  | 0.63     | 0.67  | 0.38       |
| tfidf_word_asis_syn (prev)   | 0.53      | 0.83  | 0.57     | 0.61  | 0.38       |
| tfidf_char_wb_3_5_nosyn      | 0.48      | 0.85  | 0.17     | 0.75  | 0.38       |
| tfidf_word_sublinear_syn     | 0.39      | 0.83  | 0.50     | 0.61  | 0.38       |
| tfidf_word_asis_nosyn        | 0.47      | 0.79  | 0.25     | 0.63  | 0.25       |
| tfidf_word_sublinear_nosyn   | 0.30      | 0.83  | 0.27     | 0.63  | 0.25       |

## End-to-end citation accuracy (10 grounded questions via `answers.answer`)

| method                       | citation accuracy | answered |
|------------------------------|------------------:|---------:|
| **bm25_word_syn (prod)**     | **0.90**          | 9/10     |
| bm25_word_nosyn              | 0.80              | 9/10     |
| tfidf_* rows (see caveat)    | 0.80              | 8/10     |

Production-row behaviour change vs the previous TF-IDF default:

- "How much fat is okay in my diet?" is now **answered citing
  `ADA-2026-SATFAT-10PCT`** — genuinely on-topic. The old TF-IDF answered it
  with off-topic citations (`MED-ACEI-ARB-CKD-MONITOR`,
  `DASH-2025-SODIUM-2300`) — the recorded Q5 known gap. This is an
  improvement.
- "Can I drink sweet fizzy drinks?" is now **refused** (no rule produces a
  sugar constraint and the top hits are dish chunks without citable rules).
  The old TF-IDF *refused* it as well; the un-filtered-tokenizer BM25
  prototype answered it by citing a diuretic rule — refusing is the safer,
  grounded behaviour. The underlying KB gap (no sugar-constraint rule) is
  unchanged and remains recorded in `evaluation/q_groundedness.py`.

## MIN_SCORE calibration (why the old 0.05 could not carry over)

BM25 scores are unbounded, so the TF-IDF cosine gate (0.05) does not
transfer. Measured with the bench's original raw tokenizer (no stopword
removal), stopword-only overlap drove **irrelevant** queries to BM25 scores
of 5–12 ("What is the capital of France?" scored 11.0 — above several
genuinely relevant queries), making any threshold-based refusal gate
impossible. The production tokenizer therefore filters English stopwords
(mirroring the previous `stop_words="english"`), after which the measured
distributions are cleanly separated:

- irrelevant probes (`evaluation/q_groundedness._IRRELEVANT` + typo'd
  nonsense): best score **0.0** (no vocabulary overlap);
- weakest labeled-relevant query: **2.44** (a typo-corrupted dish query);
  clean relevant queries score ≥ 3.8; grounded e2e questions 4.0–22.

`MIN_SCORE = 2.0` sits inside that gap with headroom below the weakest
observed relevant score.

## Winner analysis

`bm25_word_syn` is the unambiguous winner after the tokenizer alignment:
best hit@1 (0.638), best hit@3, best MRR (0.706), by far the best
guideline-nutrient retrieval (MRR 0.88 vs 0.53 for the previous production
TF-IDF — BM25's saturation and length normalisation stop the long verbatim
quotes from diluting the nutrient signal) and the best conflict retrieval
(0.67). Weaknesses: `topic` questions (0.49 vs 0.67 as-is TF-IDF) and typos
(hit@1 0.38, same as TF-IDF; char_wb remains the typo winner at 0.50 but is
the worst conflict method at 0.30 and cannot pass the refusal gate without
recalibration — see the previous revision of this report).

Cost/complexity: BM25 via `rank_bm25` is a drop-in replacing one vectorizer
with one `BM25Okapi` index — same chunking, same expansion function, and the
omit-zero-score contract is preserved (BM25 scores of 0 still mean "no
vocabulary overlap"; the `MIN_SCORE` gate is recalibrated as documented
above).

## Robustness notes (typos & synonyms)

- **Synonym expansion is a large, consistent win** (+0.11 MRR for as-is
  TF-IDF, +0.06 for sublinear, +0.08 for char_wb, +0.05 for BM25 under the
  production tokenizer). The `_NUTRIENT_SYNONYMS` expansion is kept in
  production. It lifts the conflict category most for BM25
  (0.63 → 0.67) and guideline (0.64 → 0.88), because queries say "salt"
  while rules say "sodium".
- **Typos** ("soduim", "protien", "calries", "fibree", "potasium",
  "phospherus", "chiken", "juce"): char_wb remains the winner (hit@1 0.50)
  as expected from sub-word matching. Word-level methods recover only via
  co-occurring query words; if typo robustness becomes a priority, a cheap
  hybrid is char_wb *re-ranking of the BM25 top-k* rather than full char_wb
  retrieval.
- Sublinear TF (`sublinear_tf=True`) still **hurts** on this corpus.

## Reproducing

```
.venv/bin/python -m backend.app.chat.retrieval_bench
.venv/bin/python -m pytest backend/app/tests/test_retrieval_bench.py backend/app/tests/test_chat.py -q
```

The run is deterministic: fixed query order, deterministic tokenizers/
vectorizers, tie-breaks on `chunk_id`, no timestamps in the artifact.
