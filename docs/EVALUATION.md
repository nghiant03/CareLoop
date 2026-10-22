# Evaluation plan

Status: proposed evaluation design incorporating confirmed constraints,
2026-10-23. Implement a reproducible evaluation command and generated report.
Run before the demonstration; an in-app evaluation dashboard is not required.
Algorithms are free to choose. No clinician or dietitian is available.

## Claims and reference data

Measure computational correctness, source fidelity, constraint satisfaction,
retrieval/citation performance, recommendation properties, and workflow integrity.
Do not claim clinical validation, improved health outcomes, patient acceptance, or
clinician agreement. Do not require clinician-labelled datasets to complete the
evaluation. Use [public data](DATA.md) and [evidence sources](EVIDENCE.md), real records first.

Expected answers must be independent of the implementation under evaluation.
Project-team transcription checks can establish exact source/table fidelity, not
clinical validity. A second LLM is not an independent clinical gold standard.
Prefer objectively checkable tasks where public gold answers exist; disclose
limitations of semantic/LLM-assisted answer scoring.

## Benchmarks

### 1. Composition arithmetic and meal logs

Reconstruct eligible NHANES 2021–2023 food intakes from matching FNDDS nutrient
values and reported grams; compare with published item and daily nutrient totals.
Use matching codes/editions and reliability filters, and derive rounding tolerances
from documentation. Report absolute/relative errors per nutrient, conversion
accuracy, missing-code coverage, and missing-nutrient rates. Handle zero reference
values without invalid relative-error calculations.

This is a software reconstruction benchmark: NHANES values were derived from
FNDDS, not independent chemical measurements. Test confirmations, quantity changes,
replacements, skipped meals, partial logs, and independent entries separately.

### 2. Rule extraction and application

Create a frozen source-grounded reference set from public guideline tables and
passages: values, units, applicability, exceptions, source locations, and expected
qualitative actions. Include age boundaries, additional-versus-total amounts,
multiple conditions, and cases requiring missing facts.

Measure extraction precision/recall, field accuracy, citation support, applicable
rule selection, target-calculation agreement, conflict handling, and missing-input
requests. Evaluate raw extracted drafts before review; separately record correction
effort so publication review does not hide extraction errors.

Use actual participant fields where available. Missing observations must not be
invented. Construct clearly labelled boundary/error cases only where public data
cannot exercise the required behaviour; these are software tests, not an invented
clinical cohort. Source holdout evaluates extraction generalization, while rule
execution is tested against published reference rules; these are distinct tasks.

### 3. Optimization

Compare the chosen informed-search/evolutionary method with greedy planning and
random search under comparable compute budgets. On small bounded instances,
compare with exhaustive or exact solutions where tractable.

Measure mandatory-constraint violations, feasible-plan discovery, normalized
nutrient deviation, dislike usage, repetition/diversity, distinctness of the three
alternatives, and wall-clock runtime for horizons 1–7 days. Report each objective
and trade-offs rather than only a combined score. Repeat stochastic methods using
recorded seeds and report variability. Independently recalculate returned plans.

Differentiate feasible solutions, best violating drafts, exhausted search budgets,
and proven infeasibility. Missing catalogue data is not zero. No violating plan
may pass as approved/usable in the workflow benchmark.

### 4. Food mining and substitutions

Compare cluster-assisted retrieval/ranking with direct nutrient nearest-neighbour
search and a simple same-category baseline. Measure restriction violations,
nutrient-target changes, category compatibility, coverage, recommendation diversity,
cluster stability, and runtime.

Use public food categories as an explicit compatibility proxy, not ground truth
for palatability. Cluster scores alone do not establish recommendation usefulness.
Show whether clustering improves a relevant outcome over the simpler baseline;
report a negative result honestly. No human taste/suitability panel is required.

### 5. Retrieval and patient answers

Prepare held-out source-grounded questions with reference passages and checkable
facts, plus patient-record questions whose expected numeric/state answers are
known. Cover general nutrition, approved targets, plan arithmetic, meal logs,
substitution explanations, incomplete evidence, and diagnosis/medication requests.

Measure retrieval recall/ranking, reference-fact correctness, citation validity
and support, numeric accuracy, approved-state compliance, clarification/referral
behaviour, latency, and actual inference consumption. Citation URL validity alone
does not demonstrate that a citation supports a claim. Report the method and
limitations of any semantic support score.

Compare grounded answers with an ungrounded baseline on a budget-bounded subset.
Freeze prompts/model identifiers and save outputs; hosted inference may change or
vary despite fixed settings. Reproduction includes deterministic report generation
from saved outputs, not a claim that fresh hosted calls are byte-identical.

### 6. End-to-end software workflows

Exercise source submission, extraction, self-review, partial approval, publication,
patient proposal completion, target approval, three plan alternatives, plan
approval, substitution review, logging, and cited explanations.

Also test retirement, new rule versions, changed allergies/observations, blocked
planning during reassessment, historical readability, and audit provenance.
These are software state-transition checks, not clinical outcome experiments.

## Experimental discipline and report

- Freeze dataset/evidence versions, selections, exclusions, prompts, algorithms,
  parameters, seeds, and environment. Report actual hardware.
- Separate development and final evaluation cases. Split records by participant,
  not by meal. Avoid near-duplicate guideline passages leaking across extraction
  development/test partitions; document any fitting/tuning on food data.
- Report US numerical benchmarks separately from Singapore catalogue coverage and
  local-food results. Do not fabricate US-to-Singapore dish equivalence.
- Report missingness and results by supported age/life-stage/condition subgroup
  where sample counts permit; disclose absent or insufficient groups.
- Decide sample sizes after the data/energy pilot, before final runs; do not tune
  against final outcomes. Include repeated-run variability and uncertainty where
  meaningful. Survey population claims require proper survey weighting/design;
  software benchmark claims do not imply population inference.
- Store downloaded data and intermediate outputs outside the checkout. Deliberately
  publish summary reports without raw participant records or credentials.
- Provide one documented entry point with data preparation, bounded pilot, full
  run, resume, and report-from-saved-results capabilities. Exact CLI syntax is TBD.
- Make missing prerequisites explicit; skipped checks are not passing evidence.
- Fit hosted calls within Neuralwatt Basic's included allowance, reserving demo
  capacity. Local deterministic tests need no hosted model.

Proposed completion criteria: zero observed mandatory-constraint violations in
released plans, correct approval transitions in all specified workflow cases,
numerical agreement within documented tolerances, and source-linked published
rules. Set extraction/retrieval quality and latency thresholds after the pilot,
before the final benchmark. These are proposed engineering gates, not clinical
certification or already-measured results.

See [implementation planning](IMPLEMENTATION.md) for delivery sequencing and status.
