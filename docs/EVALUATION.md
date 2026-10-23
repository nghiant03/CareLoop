# System evaluation

The evaluation separates four substantive experiments from supporting software
verification. Public sources and real food records come first. Unknown patient
facts, preferences, targets and food suitability are never filled to make a case
executable. No synthetic patient cohort is part of the experiments.

## Implementation and artifacts

`src/careloop/evaluation/` provides reusable Python functions, not a CLI:

- `prepare(...)`: load static team-labelled references and freeze the experiment.
- `run_pilot(directory)`: execute development cases and local experiments.
- `run(directory)`: execute/resume development and held-out test requests.
- `report(directory)`: regenerate JSON and Markdown reports without network access.
- `review.export_packets(directory)`: export model-blinded source/output packets.
- `review.import_assessments(...)`: validate and attach source-linked review labels.
- `verification.import_junit(...)`: attach supporting test results, including skips.

The reproducible system-evaluation section is in
[`notebooks/model_selection.ipynb`](../notebooks/model_selection.ipynb), alongside
the earlier development experiments. Hosted execution is disabled by default.
The notebook loads frozen summaries without credentials; full regeneration from
saved requests requires the external artifact directory.

Raw downloads, requests, responses and runtime state remain outside Git under
`~/.local/share/careloop/public/evaluation/`. Each system experiment has a
content-addressed directory containing its manifest, source/reference snapshots,
code hashes, model IDs, generation settings, per-request outcomes, local results,
verification results, and report. Published summaries exclude raw participant data
and credentials. Individual source excerpts and team reference labels are versioned.

## Frozen source references

`references.json` contains four authoritative documents, 14 passage tasks,
20 question tasks and eight no-evidence ablation selections. References include
source URLs, original-byte checksums, original locations, literal normalized
excerpts, structured rule labels, exemplar answers, and scoring notes.
They are team-labelled source references, not clinician-adjudicated gold labels.

| Split | Documents | Passages | Questions | Ablation questions |
|---|---|---:|---:|---:|
| Development | WHO sugars; KDIGO 2024 CKD | 8 | 11 | 4 |
| Test | WHO carbohydrate; Singapore HealthHub RDA | 6 | 9 | 4 |

KDIGO was used in earlier prompt development and is explicitly **not held out**.
Related passages stay in one document split. Publisher/topic overlap remains;
this small split does not establish population-wide generalization or absence of
model pretraining exposure. Test outputs must not be used to tune the tested prompts.

The evaluation loads the fixed reference files. It does not create reference labels
from evaluated outputs. Exact excerpts and reference annotations were checked
against the downloaded documents before inference.

## 1. Guideline extraction

Compare four distinct endpoint-catalogue model families:

- `glm-5.3`
- `qwen3.8-max`
- `deepseek-v4-pro-0813`
- `kimi-k3`

Each receives the production `source-rule-extraction-v2` prompt and identical
passage context. Settings: JSON mode, requested high reasoning, temperature zero,
8,192 output tokens. Provider interpretations of reasoning settings may differ.
Unsupported parameters, truncations, transport failures and schema/domain failures
are retained; there is no silent fallback or automatic retry.

Score raw drafts before review. Automatic checks compare unordered action fields,
predicates and blocker presence against the frozen references, penalizing extra
and omitted actions. These are **exact structured checks**, not full semantic
accuracy: equivalent blocked/qualitative representations and prose need review.

Model-blinded team review checks meaning, unsupported additions, applicability,
exceptions and relevance against the source. Review rationales accompany labels.
Report completed/attempted requests, bounded checks, review outcomes, latency,
provider token usage and failures separately. No correction-time or clinician-
agreement claim is made without corresponding observations.

## 2. Meal-plan search

`planning.benchmark(case)` compares the production width-32 beam search with
width-one greedy search, random complete-plan search (seeds 17, 43, 91), and exact
enumeration for spaces of at most 100,000 combinations. Random runs use the beam's
observed wall-time ceiling and a 2,000-complete-plan cap; greedy stops after its
single pass. Record effort and time because partial-plan scores and whole-plan
audits are different work units. Exact enumeration is a reference, not an equal-
budget competitor.

Cases must explicitly supply provenance, foods, facts, target actions and requested
days/schedule/item counts. `oracle.audit` independently checks catalogue snapshots,
portions, coverage, restrictions, nutrient bounds, deviation and repetition. It does
not call the production plan checker. Exact-reference gaps use the same declared
evaluation objective; absent preference observations remain unmeasured.

### Real-data prerequisite blocker

`planning_references.json` records the actual catalogue audit and official DASH
source inspection. All 2,689 acquired Singapore records have usable source portions
(3,295 in total). Planning now uses these directly at any requested meal; separate
slot/portion-enablement annotations are no longer required. Ingredient/allergen
and vegetarian/egg/dairy annotations remain unavailable. The official DASH menu
specifies nominal 2,000 kcal, not the numeric daily range required by the planner.
Its observed daily totals do not justify inventing a calorie tolerance. US menu
foods are not silently matched to similarly named Singapore dishes.

Consequently, no executable real-source planning cases are currently in the frozen
set. The harness reports **blocked**, not zero violations or successful planning.
Its unit-test fixtures verify the evaluator but are excluded from benchmark results.
Further execution needs documented target constraints and any restriction evidence
required by the selected case.

## 3. Substitution retrieval

Two scopes are reported separately:

1. **Real-catalogue retrieval:** hash-select 1,000 of the 2,689 acquired Singapore
   records, compare cluster-assisted, direct nearest-neighbour and same-category
   methods with four clusters and five results. Report result coverage, known
   nutrient distance, category agreement, recommendation diversity, missing features
   and runtime. Queries participate in fitting: this is transductive retrieval.
   Category agreement and distance are proxies, not palatability or safety labels.
2. **Checked whole-plan replacements:** for an independently valid benchmark plan,
   enumerate permitted alternative portions and independently establish feasible
   food replacements. Run the same pure recommendation core used by the API;
   measure invalid suggestions, discovery when feasible, coverage at the result
   limit, target changes and runtime. This scope is blocked until valid real-source
   planning inputs exist.

The older 300-food pilot remains a development observation in [MINING.md](MINING.md).
The current catalogue experiment is larger but is not an independent held-out
food generalization claim. No annotations are inferred from dish names.

## 4. Grounded answers

The same four families receive the production `cited-education-v4` prompt, fixed
questions and supporting passages. Four answerable questions per split also run
with **all evidence removed**. In that condition, the correct contract behaviour
is abstention rather than answering from model memory. This is a grounding ablation,
not an unrestricted medical-QA baseline.

Automatic scores cover flags, source IDs and frozen text patterns; model-blinded
review covers correctness, support and relevance. Regex matches and valid citation
IDs do not prove entailment. Review equivalent phrasing and negation against the
source. Report failures and incomplete outcomes alongside successful responses.

The frozen experiment measures the **cited-answer component with supplied evidence**.
It does not establish lexical-retrieval recall or broad persisted patient-chat
quality. Patient-context chat and stale-history behaviour are covered by supporting
software tests; a real-record patient-question benchmark remains unmeasured.

## Supporting verification

Arithmetic, rule execution, predicate boundaries, missing facts, conflicts,
imports, persistence and permissions are correctness tests, not headline experiments.
The PostgreSQL test suite also covers publication, approval, revision, retirement,
reassessment, interruption, duplicate requests and audit history.

`test_evaluation_workflow.py` exercises plan generation/approval, replacement
recommendation/draft/approval, intake, cited chat, idempotency and invalidation after
a food revision. It uses existing explicitly labelled software-test fixtures and a
stub provider. It is an acceptance test, not a real-patient or hosted-answer result.

Verification commands:

```sh
uv run --with pgserver==0.1.4 python tests/run_postgres.py -q --junitxml=/tmp/opencode/careloop-evaluation/verification.xml
uv run ruff check src tests
uv build
```

## Reproduction

Run the following from installed project code or the notebook; there is no CLI:

```python
from pathlib import Path
from careloop.evaluation import prepare, run_pilot, run, report

food_export = Path.home() / ".local/share/careloop/public/sgfoodid/kaggle-v1" / (
    "normalized-dc5bea6d2bb1c450e46a5e61307cab69ec40db4dc0c4f0e1d5a6df2352317fac-0.jsonl"
)
experiment = prepare(food_export=food_export)
# Explicit hosted work; credentials are required only for these calls.
# run_pilot(experiment)
# run(experiment)
summary = report(experiment)  # Offline, from saved outcomes.
```

Frozen manifests cannot be overwritten with changed inputs. Requests are claimed
before inference; rerunning retains successful, failed and interrupted-pending
records without repeating provider calls. Fresh calls after changes require a new
experiment. Report regeneration requires neither credentials nor network access.
Hosted outputs may vary even at temperature zero; cache reproducibility is not a
claim of byte-identical future inference.

## Interpretation

No human usability study, clinical validation, clinical outcomes, taste panel or
clinician workload reduction is claimed. Missing prerequisites and unperformed
review are explicit. Counts and failures matter more than a single aggregate score;
four documents cannot support broad confidence claims across all supported conditions.
