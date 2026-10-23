# Evidence sources and ingestion

Status: authoritative-domain link discovery, URL/PDF acquisition, page/heading
passages, lexical retrieval, refresh comparisons, and structured numeric conflict
checks are implemented, 2026-10-23. Hosted extraction creates review-blocked drafts
through the API and reviewer workspace using GLM 5.3 by default. Broader clinical
interpretation/reference evaluation remains pending.
Food and participant datasets are documented separately in [DATA.md](DATA.md).

## General nutrition and life stages

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
