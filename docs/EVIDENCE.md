# Evidence sources and ingestion

## Condition coverage expansion, published 2026-10-24

Published 28 additions in `a3514ad6-92b4-42bc-b863-46cf4475dd35`, bringing the active
catalogue to 52 rules. These are user-authorized AI source reviews, not independent
clinician sign-off. Required assessments, optional guidance and executable targets
remain separate; adding a rule does not imply an enforceable numerical constraint.

| Population | New coverage | Source |
|---|---|---|
| CKD, including children | Plant-forward/less-ultraprocessed diet guidance; individual sodium/phosphorus/potassium/protein review | KDIGO 2024, 3.3.1–3.3.2 |
| Adult CKD | Protein-suitability assessment; G3a/G3b/G4/G5 each have a 0.8 g/kg/day soft protein reference, excluding dialysis/pregnancy/lactation | KDIGO 2024, 3.3.1.1 and 3.3.1.3 |
| Paediatric CKD | Growth-specific energy/protein assessment; do not impose protein restriction | KDIGO 2024, 3.3.1.4 |
| Adolescents 11 to under 18 | Fibre minimum 25 g/day; fruit/vegetable minimum 400 g/day, subject to individual therapeutic review | WHO Healthy diet |
| Hypertension | DASH components; lower-sodium food alternatives | HPB Lifestyle Prescriptions |
| Prediabetes | Wholegrain/protein/vegetable meal pairing; inherited salt/sugar/soluble-fibre advice | HPB Lifestyle Prescriptions |
| Type 2 diabetes | Inherited wholegrain substitution; meal pairing | HPB Lifestyle Prescriptions |
| Type 2 diabetes at hypoglycaemia risk | Wholegrain substitution; meal pairing; required alcohol-risk review | HPB Lifestyle Prescriptions |
| Pregnancy | Calcium reference review; adult pregnancy iron reference review | Singapore RDA |
| Breastfeeding | Calcium reference review; adult lactation B12 reference review | Singapore RDA |
| Dialysis | Separate protein, potassium and phosphorus assessments | NKF protein/potassium/phosphorus pages |
| Gout | Balanced diet and limits of diet evidence; weight-related counselling | NICE NG219 1.4.1–1.4.2 |

Adult CKD protein is an `intake` fit reference, not a hard ceiling; the required
suitability review addresses metabolic instability, nutrition status and appropriate
body weight. Paediatric CKD targets require age/growth-specific assessment. No
universal renal potassium/phosphorus restriction is introduced. Calcium, iron and
B12 remain assessment-only because food composition/planner support is absent;
these RDA references are not supplement prescriptions. Dialysis remains outside
the supported planning population despite the new review guidance. Condition
labels still use the exact documented vocabulary; seizure disorders and other
unreviewed diagnoses do not gain disease-specific coverage from this expansion.

The adolescent additions use a conservative age >=11 and <18 subset of the quoted
WHO “older than 10” scope. Age 10 to under 11 remains a coverage gap requiring
source-boundary review; existing 2–5/6–9 bands are unchanged. General targets must
still be reviewed for individual renal needs rather than treated as therapeutic
prescriptions solely because they match age.

Acquisition retained original HTML, SHA256 metadata and extracted text externally
for [NKF protein](https://www.kidney.org/kidney-topics/ckd-diet-how-much-protein-right-amount),
[potassium](https://www.kidney.org/kidney-topics/potassium-your-ckd-diet),
[phosphorus](https://www.kidney.org/kidney-topics/phosphorus-and-your-ckd-diet), and
[NICE gout](https://www.nice.org.uk/guidance/ng219/chapter/Recommendations).
These four were registered through the text-source API; the acquired-document
allowlist was not changed. Original KDIGO/WHO/HPB/RDA snapshots were reused.
Every rule quotation was checked against the retained source before publication.

Audit directory: `~/.local/share/careloop/reviews/2026-10-24/condition-expansion/`.
It contains source snapshots, `plan.json`, events, conflicts, publication,
read-back catalogue and `coverage-matrix.json`. The publication had zero blocking
conflicts and 21 reviewed overlaps (dietary pattern, protein, meal composition,
calcium, wholegrains and alcohol). Repeating the publisher made no changes:

```sh
uv run python -m careloop.evidence.condition_rules --sources ~/.local/share/careloop/reviews/2026-10-24/condition-expansion/sources.json --output ~/.local/share/careloop/reviews/2026-10-24/condition-expansion --apply
```

Omit `--apply` to prepare only. The publisher preserves unrelated drafts, rejects
changed/ambiguous owned rules, supports resuming identical drafts, and verifies
published revisions by read-back. Create fresh target proposals to use these rules;
historical patient facts and approvals were not rewritten.

## Published-rule category review, 2026-10-24 (application pending)

All 24 active rules were reviewed against their retained quotations. The explicit
manifest at `~/.local/share/careloop/reviews/2026-10-24/rule-categories/review.json`
records each original body/revision, proposed classification and rationale:

| Category | Count | Reviewed scope |
|---|---:|---|
| Executable target | 10 | Six adult WHO limits/minimums, two child fibre minimums, CKD sodium, hypertension sodium |
| Required assessment | 8 | Individual energy, pregnancy/lactation totals, diabetes portions/timing, hypoglycaemia meal consistency, sodium-wasting nephropathy, CKD G4/G5 assessment |
| Advisory guidance | 6 | Dietary variety, carbohydrate quality, fat quality, protein-source variety, prediabetes wholegrain substitution, gout alcohol counselling |

This is user-authorized AI source review, not independent clinician sign-off.
Classification changes do not alter the clinical actions, quotations, population
predicates or exceptions. Four general WHO advisory rules now need no mandatory
disposition; individual energy assessment remains required. Preview evaluation of
Synthea `0149d553` produced six applicable targets, one required energy assessment,
four advisory rules and 13 not-applicable rules. The preview is not a saved target.

`review_role` is explicit (`required` by default; `advisory` only for assessment
actions with a review note). The extraction provider continues producing required,
review-blocked drafts; it does not decide what becomes optional. Reviewers can
change classification in the structured editor. Patient evaluation derives target
versus required-assessment capability from supported actions/units and preserves
the explicit advisory role. See [patient selection](PATIENTS.md#rule-categories-and-selection).

The running API lacks this field. The apply attempt refused before any catalogue
write; Docker permission is denied in the agent session. After rebuilding:

```sh
sudo docker compose up --build -d api web
uv run python -m careloop.evidence.categorize_rules --review ~/.local/share/careloop/reviews/2026-10-24/rule-categories/review.json --apply
```

The command validates classification-only changes, resolves the full batch before
writing, rejects stale/unrelated drafts, resumes identical revisions, checks
conflicts and verifies publication by read-back. Fourteen assessment rules get
explicit reviewed classification revisions; the ten numeric rules need none.
Re-running is idempotent. Generate fresh patient proposals after publication;
historical proposals retain their original evaluations and approval workflow.

Status: authoritative-domain link discovery, URL/PDF acquisition, page/heading
passages, lexical retrieval, refresh comparisons, and structured numeric conflict
checks are implemented, 2026-10-23. Hosted extraction creates review-blocked drafts
through the API and reviewer workspace using GLM 5.3 by default. Broader clinical
interpretation/reference evaluation remains pending.
Food and participant datasets are documented separately in [DATA.md](DATA.md).

## General nutrition and life stages

### Executable general and concrete rules (published 2026-10-24)

`src/careloop/evidence/diet_rules.py` prepares nine reviewed numeric rules from the
retained WHO and KDIGO sources. It revises matching assessment rules instead of
duplicating them: adult fruit/vegetables >=400 g/day, fibre >=25 g/day, free sugars
<10% energy, saturated fat <=10% energy, sodium <2,000 mg/day, and child fibre
>=15 g/day (2–5) / >=21 g/day (6–9). It adds adult trans fat <=1% energy and an
adult CKD sodium <2,000 mg/day rule requiring explicit CKD presence. Sodium rules
carry the sodium-wasting-nephropathy exception and therapeutic-review context.
The existing hypertension rule remains separately source-scoped. CKD protein
restrictions still require source-context/suitability review, especially in cancer,
malnutrition or metabolic instability; no universal protein restriction is added.

Age >=18 is an explicit reviewer-selected adult subset. Child age bands preserve
the retained source's stated boundaries. No rule supplies a universal energy
prescription. Missing free-sugar/trans-fat/food-group composition blocks food
eligibility rather than inventing zeros. The capability now exists independently
of completeness of the current food catalogue. Percentage, minimum and strict
ceiling semantics are documented in [planning](PLANNING.md).

The plan and publication audit are retained at
`~/.local/share/careloop/reviews/2026-10-24/executable-diet/`. After the user rebuilt
API/web, all nine rules were published and read-back verified in publication
`1ad13384-0ecd-4da1-b5ce-3a5e53e00be7`; the catalogue now has 24 active rules.
There were no blocking conflicts. Two sodium overlap findings were covered by the
recorded review of strict WHO/KDIGO limits versus the inclusive hypertension limit.
The initial attempt stopped at duplicate child-fibre extraction drafts. Matching
now prefers the unique published rule, preserves unrelated drafts, and resolves
the entire batch before writing. Existing identical revisions resume without a
new revision. Both blocked child extraction drafts remain unchanged at revision 1.
To repeat the deployment/update from the repository root:

```sh
sudo docker compose up --build -d api web
uv run python -m careloop.evidence.diet_rules --output ~/.local/share/careloop/reviews/2026-10-24/executable-diet --apply
```

The command retains the source snapshot/plan, revision events, conflict report and
publication response, verifies active revisions by read-back, and is idempotent.
Omit `--apply` to prepare without API writes. Publication marks affected targets
for review; regenerate proposals and obtain clinician approval separately.
Unknown/ambiguous source matches or blocking conflicts stop the update. The
historical publication below records the earlier assessment-only baseline.

### Published adult baseline, 2026-10-24

Following a user-requested coverage review, nine adult baseline rules were added
and published from WHO Healthy diet (live page checked against retained source
`168c9131-2b3b-404f-a84e-5e737cb13ef4`). Topics: dietary variety, individualized
energy balance, wholegrain/pulse carbohydrate sources, fruit and vegetables
(at least 400 g/day), naturally occurring fibre (at least 25 g/day), free sugars
(less than 10% energy, optional further reduction), unsaturated-fat substitutions,
saturated/trans-fat energy limits, and salt/sodium reduction. Age >=18 is an
explicit reviewer-selected adult subset, not a claim that the source excludes
younger populations. The existing general protein guidance remains published.

These are `assessment` rules: the current planner cannot faithfully enforce
food-group gram totals, minimum-only intakes, strict inequalities or percentages
of individualized energy through these actions. Values remain in the advice and
verbatim quotes; none is converted into a universal 2,000 kcal diet or an invented
gram target. General advice does not replace therapeutic diets. Sodium guidance
explicitly requires review of sodium-wasting nephropathy and potassium-salt risk.

Publication `523d7c9e-bd76-4f39-8f88-e10ee878bcfd` brought active rules from 13 to
22. Zero blocking conflicts; seven overlaps were explicitly reviewed (energy vs
pregnancy/lactation, carbohydrate quality vs diabetes-related guidance, sodium vs
hypertension/nephropathy). Actor is labelled user-authorized AI demo review, not
independent clinician sign-off. No patient facts or target approvals were changed.
Read-back verified all nine published revisions; 36 engine checks covered a healthy
adult, MIMIC 10003046 revision 2, a child and unknown age. Adult cases produce
`needs_clinician`, children `not_applicable`, and unknown age `incomplete`.

Audit scripts, source snapshot, review plan, conflict report, publication response
and verification are retained outside Git in
`~/.local/share/careloop/reviews/2026-10-24/general-diet/` (script in its parent).
Initial creation of an energy quote concatenated nonadjacent passages and was
rejected by the API's verbatim check; changed to a contiguous retained excerpt
before approval. Existing identical drafts were reused on retry.

- [Singapore RDA tables](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/recommended_dietary_allowances):
  age/sex/life-stage recommendations. Observed page review date: November 2022.
  Check references, footnotes, age boundaries, and additions versus total amounts.
- [My Healthy Plate](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/plan-your-meals-with-my-healthy-plate):
  food-group guidance and explanations, not a universal energy prescription.
- [Kids and teens](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/a-healthy-food-foundation-for-kids-and-teens):
  age-specific food-group guidance.
- [Pregnancy guide](https://www.healthhub.sg/well-being-and-lifestyle/personal-care/healthy-start-for-your-pregnancy):
  public guide/PDF and pregnancy nutrition material.
- [WHO healthy diet](https://www.who.int/news-room/fact-sheets/detail/healthy-diet):
  overview and discovery links to original guidelines.
- [WHO carbohydrates](https://www.who.int/publications/i/item/9789240073593) and
  [WHO sugars](https://www.who.int/publications/i/item/9789241549028):
  recommendations, populations, qualifications, and supporting evidence.

Energy-estimation formulas and weight-management methods still need dedicated
source selection. Numeric reference intakes, ceilings, ranges, and qualitative
guidance must remain distinct.

## Conditions and complications

- [HPB Lifestyle Prescriptions](https://www.primarycarepages.sg/healthier-sg/lifestyle-prescriptions):
  prediabetes/diabetes, hypoglycaemia risk, hypertension, lipid/CV-risk guidance,
  including meal timing and carbohydrate consistency.
- [ACE repository](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/):
  authoritative local discovery entry point; select nutrition-relevant sections.
- [ACE hypertension](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/hypertension-tailoring-the-management-plan-to-optimise-blood-pressure-control/)
  and [ACE lipids](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/lipid-management-focus-on-cardiovascular-risk/).
- [Healthier SG multimorbidity](https://www.primarycarepages.sg/healthier-sg/care-protocols/chronic-care-protocols/multimorbidity-diabetes-hypertension-and-hyperlipidaemia):
  interacting conditions and individualized kidney-related dietary management.
- [KDIGO 2024 CKD guideline](https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf):
  protein, sodium, potassium considerations, and qualifications for stage, age,
  metabolic instability, frailty, and other patient circumstances.

Do not apply universal potassium restriction to CKD or adult protein rules to
children. Extract full applicability and exceptions. A source's availability does
not establish that required patient facts or food attributes are available.

## Loading and publication

1. Discover documents within approved authoritative domains, or accept reviewer
   URLs, PDFs, and pasted text. Present discoveries for selection/extraction.
2. Retain source content and metadata. Parse text, tables, headings, footnotes,
   and page/section references; report extraction failures explicitly.
3. Build linked searchable passages for chat and structured draft rules for
   computation. See [inference](INFERENCE.md) for hosted-model configuration/selection.
4. Validate units, applicability, supporting passages, and conflicts. Model output
   must not activate itself as a published rule.
5. Reviewers edit/approve individual rules or selected source-batch members, then
   explicitly publish a versioned batch. One reviewer and self-approval suffice.
6. Patient proposals reference the published version and supporting rules;
   clinician completion/approval is a separate workflow.
7. On-demand refresh creates drafts and differences. Published changes and
   retirement flag affected patient targets; preserve historical explanations.

Audit who changed what, when, why, and source support. Missing evidence is not an
invitation to invent a numeric recommendation. Resolve conflicts through explicit
applicability and reviewer decisions, not automatic strictest-value selection.

## Implemented acquisition API

- `GET /api/evidence/discovery-seeds` lists the approved exact hostnames and research
  entry points. `POST /api/evidence/discover` takes reviewer actor/reason, an approved
  HTTPS page URL, and optional keyword query. It returns at most 100 matching links
  from that page, filtered to the approved hosts. This is bounded page-link discovery,
  not a web-wide search engine or automatic crawler.
- `POST /api/evidence/source-imports` accepts reviewer actor/reason, title, edition,
  and either `url` or `pdf_base64`. PDF uploads also require a provenance `locator`.
  Reviewer text submission continues through `/api/evidence/sources`.
- PDF `first_page`/`last_page` optionally select a range of original 1-based pages.
  This permits large guidelines to be imported in relevant sections. The entire
  original PDF is retained; extracted coverage is explicitly recorded.
- Acquisition validates every redirect, allows only HTTPS on approved hostnames,
  resolves public addresses and pins the connection address with TLS hostname
  verification. Files are bounded at 10 MB. PDFs use PaddleOCR 3.7.0 PP-StructureV3
  with PaddlePaddle 3.3.1, in a separate spawned process. Compose uses the official
  CUDA 12.9 wheel (`ocr-gpu` extra) and reserves NVIDIA GPU 0. The GPU extra
  uses explicitly pinned NVIDIA CUDA runtime, NVRTC, cuBLAS, cuDNN, cuSOLVER,
  cuSPARSE, cuFFT, cuRAND and NCCL packages: the inspected Paddle wheel does not
  bundle those shared libraries. Docker supplies their `LD_LIBRARY_PATH`; direct
  parsing configures it before spawning the OCR worker. `CARELOOP_OCR_DEVICE`
  selects `gpu:0` or `cpu`; direct development defaults to CPU. Layout recognition,
  OCR and table recognition are enabled; formula/chart recognition is disabled.
  oneDNN is disabled because the pinned Paddle CPU layout executor rejected PIR
  double-array attributes during verification; this keeps the same recognition models.
  `pypdf` only validates and selects pages; it no longer extracts production text.
  Limits are 500 pages, ten million parsed characters, and a configurable
  `CARELOOP_OCR_TIMEOUT` (default 7,200 seconds). There is no silent truncation.
- Original PDF page numbers and layout block locations are retained. Model weights
  and atomic per-page layout JSON are cached below `CARELOOP_DATA_DIR`; completed
  pages are reused after interruption. The first run downloads PaddleOCR models.
  Docker includes `ocr` and `ocr-gpu`; CPU development installs use
  `uv sync --extra ocr --extra ocr-cpu`. The CPU/GPU wheel extras are mutually
  exclusive. Completed page caches are reused across devices; new page artifacts
  record the device used. Switching devices does not reset completed source jobs.
  On the verified development host, Paddle import required
  `__GLX_VENDOR_LIBRARY_NAME=nvidia` and
  `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json`
  before Python startup to avoid a Mesa/system-LLVM conflict. This is a host-specific
  workaround requiring that NVIDIA vendor manifest; container verification is separate.
- HTML retains native tables, merged cells, header/unit rows, hierarchical headings,
  and preceding paragraph context. Page navigation, scripts and footers are excluded;
  streamed/accordion content is retained even when initially hidden. HTML requires
  UTF-8. Tables remain whole rather than losing unit rows during row splitting.
- Passages preserve complete table blocks and sentence boundaries, with a 9,000
  character quotation budget. Oversized indivisible tables/blocks fail explicitly.
  OCR text/numbers and table interpretation still require source review. Encrypted,
  malformed, empty/unrecognized, and over-limit inputs fail explicitly.
- Original bytes, checksums, retrieval/parser metadata, and passages are stored in
  PostgreSQL. Download originals via `/api/evidence/sources/{id}/document`; original
  HTML is served as a download rather than rendered application content.
- `/api/evidence/sources/{id}/passages` returns paginated location-labelled text and
  exact offsets into the saved extracted content. `/api/evidence/passages?q=...`
  uses PostgreSQL lexical retrieval, defaulting to sources with active published rules.
  Reviewer discovery may set `published_only=false`. A published source's other
  passages are not themselves structured, approved rules.
- `refresh_of` creates a new source snapshot and line-difference summary. Existing
  sources/rules remain unchanged; request extraction and review explicitly for the
  new snapshot. Refresh never publishes recommendations.

## Hosted rule extraction

`POST /api/evidence/sources/{id}/extractions` requires a reviewer actor/reason,
`request_id` (UUID), and `passage_ordinal`. The optional `model` defaults to
`glm-5.3`; use `GET /api/inference/models` to discover overrides. It extracts at
most three rules from one saved passage.
Optional `generation` sets response mode, reasoning effort, temperature, and token
budget; see [inference](INFERENCE.md#output-format-and-reasoning). The default is
strict JSON Schema with a 4,096-token cap. No database connection is held during inference.

The run is committed as `pending` before the call. Reusing its ID with the same
inputs returns its state without another call; changing inputs returns a conflict.
Read results through `GET /api/evidence/sources/{id}/extractions/{request_id}`.
`GET /api/evidence/sources/{id}/extractions` lists newest-first runs with bounded
`limit`/`offset` pagination. `/reviewer/evidence` supports passage selection,
extraction reasons, pending/failure/empty results, limitations, and opening each
generated draft in the structured editor. Refreshing a run never calls the provider.
The UI explicitly requests JSON mode, high reasoning, and an 8,192-token budget.
The rule list and structured editor display the rule's saved source title and
edition, linking HTTP(S) locators to the original source. Attribution follows the
rule's `source_id`, even when another source is selected in the library.
The review workspace supports combined text, status, source, subject, blocker,
and selected-only filters. Text search covers advice, population, applicability,
quotation and source title. Selections persist across filters; the result count
identifies hidden selections, and review actions apply to the complete selection.
Select-visible excludes retired rules. Acquisition, retained source text, supporting
quotes and saved extraction runs use expandable sections. Run history opens after
a new extraction completes; pending-request recovery stays visible.
Retained HTML tables in evidence are rebuilt as allowlisted React elements in
source previews, extraction passages, rule quotations, target citations and chat
citations. Table headers, row/column spans and source wording are preserved;
wide tables scroll in a named keyboard-focusable region. Source scripts, event
handlers, styles, images and links are not injected. Plain-text comparisons remain
literal. Original stored evidence and verbatim editor fields are unchanged.
Extraction prompt v3 supports explicit `has_ckd` boolean predicates independently
of stage; it does not infer CKD from eGFR or missing information.
A crash can leave a pending run with an unknown provider outcome; it is not retried.

Schema-invalid, truncated, or unsupported-predicate outputs produce a failed run and
no drafts. The server attaches the selected passage verbatim as each draft's quote;
models do not generate quotation text. Runs retain prompts, prompt version, model,
schema/generation settings, response/usage, and an endpoint fingerprint, but no
credentials. Valid results create ordinary rule drafts with a
mandatory review blocker. Reviewers must edit them to resolve applicability,
exceptions, and surrounding context before approval and explicit publication.
The selected passage may omit essential context; validation does not establish
clinical correctness. Failure/empty extraction is not evidence that no rule exists.

### Real-source check

Downloaded the official KDIGO guideline (5,966,902 bytes; SHA-256
`b18db280f7dc889a1a99447b779c0312cd536f939a5180b38894a5d68e4410c0`).
The full document exceeded the text limit. Selecting original PDF pages 65–75
produced 91,489 characters and 57 passages from a 199-page document. Verified
original-byte retrieval, first-page passage retrieval, and source metadata through
the API in temporary PostgreSQL. No rules were published; the database was removed.
The PDF and acquisition report remain outside Git under
`~/.local/share/careloop/public/evidence/`. This verifies ingestion, not clinical
interpretation of those passages.

### Frozen evaluation sources

The [system evaluation](EVALUATION.md) adds downloaded official WHO sugars (2015),
WHO carbohydrate (2023), and Singapore HealthHub RDA snapshots alongside KDIGO.
Static team-labelled references retain 14 passage tasks, 31 source excerpts and
20 questions. Original-file checksums and excerpt locations are in
`src/careloop/evaluation/references.json`; full downloads remain outside Git.
KDIGO and WHO sugars are development documents; WHO carbohydrate and HealthHub
are held out for the frozen comparison. These reference files are evaluation inputs,
not automatic publication of clinical rules into the application.

## Structured conflict analysis

`POST /api/evidence/conflict-check` takes the same reviewer/rule selection as batch
approval. It returns a catalogue generation and checks the selected revisions against
one another and active rules, replacing older active versions of selected rules.

Supported numeric bounds, equality predicates, and list membership establish whether
populations may overlap; exceptions negate their individual predicates, consistent
with the applicability engine. Disjoint same-unit ranges, or a range above a ceiling,
block publication when the structured populations overlap. Publication reruns this
check transactionally and audits its result.

Different targets, units, qualitative guidance, and unsupported predicates produce
review findings rather than fabricated conversions or semantic verdicts. The
required manual conflict-review note and catalogue-generation binding remain.
Clinical free text, correlations between patient facts, and cross-nutrient conflicts
are outside this analyzer; absence of a blocker is not proof of clinical consistency.

## Local source-review checkpoint, 2026-10-24

A user-authorized AI review published 12 revisions/new rules through the audited
API, under an explicitly AI-labelled demo reviewer. This is not independent
clinician sign-off. One rule supplies the HPB hypertension sodium ceiling of
2,000 mg/day, with a reviewer-added, KDIGO-supported sodium-wasting-nephropathy
exception. Eleven are clinician-assessment guidance covering child fibre intake,
pre-diabetes/type-2 diabetes/hypoglycaemia risk, pregnancy/lactation, CKD G4/G5,
sodium-wasting nephropathy and gout. The two CKD stages use separate equality
rules rather than an invalid conjunction. Pregnancy increments require assessment
of trimester and baseline and are not summed automatically with lactation values.

The published protein range with an unsupported age-40 threshold and complementary
feeding exclusion scoped to everyone aged one or older were retired with history
retained. Alcohol moderation was revised from universal exclusion to a gout-scoped
assessment. There are 13 active rules after this batch, including the pre-existing
mixed-protein-source assessment. Publication ID:
`51e1af32-208f-4d3a-af3d-5888aefe7993`.

Review found that the planner does not enforce minimum-only `intake` values;
child fibre recommendations were therefore published as assessment guidance,
not claimed as enforced lower bounds. This batch does not supply the complete
numerical targets or clinician-approved energy range required for meal planning.

Verification: model validation and positive/negative/unknown applicability cases
for all 12 rules, four final sodium-exception cases, API conflict analysis with
zero blocking conflicts and four individually reviewed qualitative overlaps,
and catalogue read-back of every published revision and both retirements.
Source snapshots, review reasons, execution scripts, conflict findings and
read-back results are retained outside Git at
`~/.local/share/careloop/reviews/2026-10-24/`.
