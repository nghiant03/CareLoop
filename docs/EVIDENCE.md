# Evidence sources and ingestion

Status: authoritative-domain link discovery, URL/PDF acquisition, page/heading
passages, lexical retrieval, refresh comparisons, and structured numeric conflict
checks are implemented, 2026-10-23. Hosted rule extraction and broader clinical
interpretation/reference evaluation remain pending.
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
   computation. See [inference](INFERENCE.md) for hosted-model selection/budget.
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
  verification. Files are bounded at 10 MB. PDF parsing uses a separate Linux
  process with a 512 MiB memory limit, 12-second CPU limit, 20-second wall limit,
  500-page document limit, and one-million-character text limit. Oversized sources
  require page selection or reviewer-supplied text, not silent truncation.
- Text extraction records PDF page numbers or HTML heading labels, preserves table
  text/layout where possible, and emits reviewer warnings. It does not perform OCR
  or certify correct table/footnote interpretation. Empty/scanned-only, encrypted,
  malformed, and over-limit inputs fail explicitly. HTML imports currently require UTF-8.
- Original bytes, checksums, retrieval/parser metadata, and passages are stored in
  PostgreSQL. Download originals via `/api/evidence/sources/{id}/document`; original
  HTML is served as a download rather than rendered application content.
- `/api/evidence/sources/{id}/passages` returns paginated location-labelled text and
  exact offsets into the saved extracted content. `/api/evidence/passages?q=...`
  uses PostgreSQL lexical retrieval, defaulting to sources with active published rules.
  Reviewer discovery may set `published_only=false`. A published source's other
  passages are not themselves structured, approved rules.
- `refresh_of` creates a new source snapshot and line-difference summary. Existing
  sources/rules remain unchanged; extracted draft rules still require the subsequent
  hosted extraction/review workflow. Refresh never publishes recommendations.

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
