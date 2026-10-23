# Public data plan

Status: NHANES, FNDDS, and the supplied Kaggle SG FoodID mirror are implemented
and downloaded, 2026-10-23. Broader participant-component integration and ingredient/
allergen coverage remain incomplete. Source-specific audits are recorded below.

## Acquisition principles

- Public downloads only; do not depend on registration, institutional access, or
  clinician-provided datasets. Real data first, generation only as a last resort.
- Singapore/SEA is the application food context. US survey data may support
  reproducible benchmarks but is not evidence of Singapore representativeness.
- Keep raw datasets outside source control and container images, under
  `~/.local/share/careloop/public/` by default.
- Record source identity, URL, edition/date, retrieval time, units, applicability,
  and transformation provenance. Preserve source snapshots supporting active and
  historical rules. Missing values are unknown, not zero.

## Public data candidates

### Local food composition

- [HPB SG FoodID](https://www.hpb.gov.sg/healthy-living/food-and-beverage/sgfoodid/)
  advertises searching, comparing, and downloading Singapore food information.
  Verify export mechanics, reuse terms, nutrient completeness, portions, and
  ingredient/allergen coverage before relying on it as the primary catalogue.
- [Open Food Facts downloads](https://sg.openfoodfacts.org/data) can supplement
  packaged foods. ODbL terms apply; coverage and ingredient completeness vary.
  It does not certify mixed-dish or vendor allergen suitability.

### Participant records and numerical benchmarks

- [NHANES 2021–2023](https://wwwn.cdc.gov/nchs/NHANES/continuousnhanes/default.aspx?Cycle=2021-2023):
  public demographics, measurements, questionnaires, and laboratory components.
- [NHANES dietary downloads](https://wwwn.cdc.gov/nchs/NHANES/search/datapage.aspx?Component=Dietary&Cycle=2021-2023):
  DR1IFF_L/DR2IFF_L food-level recalls and DR1TOT_L/DR2TOT_L nutrient totals;
  link by participant identifier SEQN. Apply documented reliability/status filters.
- [USDA FNDDS downloads](https://www.ars.usda.gov/northeast-area/beltsville-md-bhnrc/beltsville-human-nutrition-research-center/food-surveys-research-group/docs/fndds-download-databases/):
  matching 2021–2023 food codes, portions/weights, ingredients, nutrients, and
  food categories. Public spreadsheets and other download formats are available.
- [FoodData Central downloads](https://fdc.nal.usda.gov/download-datasets/):
  another public distribution route for FNDDS and composition data; distinguish
  food/nutrient identifier systems and dataset editions.

NHANES provides survey respondents, not approved clinical care histories. Do not
invent diagnoses, preferences, allergies, or approvals for them and call those
observed data. Usually up to two nonconsecutive recall days are available, not
months of individual adherence. Required patient fields and subgroup coverage
must be audited. Reference dietary totals derive from FNDDS, so reconstruction
checks software correctness rather than independently validating food chemistry.

UK NDNS was investigated but is not a primary choice: access requires registration
and an end-user agreement, contrary to the public-download-only constraint.

## Implemented participant acquisition

`ingestion.acquire("nhanes", directory, 100)` downloads
[DEMO_L XPORT](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.xpt)
and writes immutable-content-named raw data, normalized CSV, and a manifest outside
the checkout. The [current codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.htm)
is recorded in the manifest. Acquisition checks the XPORT header because a CDC
page-not-found response can return HTTP 200.

The adapter maps **only SEQN and RIDAGEYR** to external identity and observed
survey age. Sex, diagnoses, pregnancy, labs, measurements, allergies, and preferences
remain unknown. It does not infer absent conditions or create approvals. Exact
observation date is unknown; the provenance records the survey edition instead.
Age 80 is top-coded (80 or older), so those records are excluded rather than treated
as exact age 80. The adapter supports ages 2–79 inclusive; this dataset limit
does not narrow the application's broader age-2+ requirement.

Observed acquisition on 2026-10-23 (local date), using pandas 3.1.0:

| Result | Count |
| --- | ---: |
| Source records | 11,933 |
| Below age 2 | 368 |
| Top-coded age 80+ | 525 |
| Missing age | 0 |
| Eligible records | 11,040 |
| Prepared and verified through CSV API | 100 |

Raw SHA-256:
`ca4374a158b493b8b0163e1388da21d57a18d1b9cecff2aa4e2fa2bec494fe23`.
The XPORT reader decoded some zero ages as a tiny positive float; these remain
excluded by the under-2 filter. Eligible ages must be whole numbers and are never
rounded. Invalid/duplicate respondent IDs or unexpected eligible ages fail import.

Selection is the lowest eligible SEQN values up to `--limit` (1–5,000), deterministic
but **not representative**. The adapter does not perform survey-weighted analysis.
The manifest contains retrieval time, raw and CSV checksums, all available columns,
mapped and unknown fields, transformation identifier, counts, and selection policy.

The actual 100-record CSV was imported successfully through HTTP into temporary
PostgreSQL during verification, then that test database was removed. No persistent
application database was populated by that verification. Use `--import-records` with the documented
database URL to import explicitly; duplicate external identities roll back the batch.

### Local stratified sample, 2026-10-24

A user-authorized one-off import populated the running local application with 32
NHANES respondents. This is separate from the age-only adapter above. Selection
uses the lowest unused SEQN: two per recorded sex in each age band 2–5, 6–9,
10–17, 18–39, 40–64 and 65–79, plus two each with recorded pregnancy, reported
hypertension without reported diabetes, reported diabetes without reported
hypertension, and both reports. It is a convenience sample, not representative.

Official DEMO_L, BPQ_L, DIQ_L and BMX_L files were joined one-to-one on SEQN.
Mappings were checked against their CDC codebooks: RIDAGEYR (age), RIAGENDR
(recorded male/female), RIDEXPRG 1/2 (pregnant/not pregnant at examination),
BMXWT/BMXHT (measured kg/cm), BPQ020=1 (self-reported professional hypertension
diagnosis), and DIQ010=1 (self-reported diabetes, type unspecified). Unknowns and
unmapped facts remain null; borderline diabetes is not mapped to pre-diabetes.
Positive condition reports are not an exhaustive clinical diagnosis inventory.
Interview age and examination measurements/status have different observation
contexts; exact dates are unavailable. No CKD stages or diabetes types were inferred.

Read-back verified all 32 records and provenance: 15 male, 17 female, two recorded
pregnancies, nine hypertension reports, five diabetes reports (groups overlap),
27 measured weights and 26 measured heights. No targets or plans were approved.
Raw data remain under the public-data directory; selection scripts, component
checksums, raw selected fields, CSV and verification results are retained outside
Git in `~/.local/share/careloop/reviews/2026-10-24/`. Verification used the CSV
import API followed by `GET /api/patients/{id}` for every imported record.

## Food ingestion

### Singapore: supplied Kaggle SG FoodID mirror

The user supplied [Comprehensive Food Nutritional Information](https://www.kaggle.com/datasets/adisongoh/comprehensive-food-nutritional-information/data).
Its public API permits anonymous metadata and version-1 ZIP downloads. The uploader
attributes it to SG FoodID and declares **CC0: Public Domain**; this is a third-party
mirror, not an official HPB release endpoint. Uploader: `adisongoh`; version 1 was
updated 2026-07-20. Metadata and source attribution are retained with the raw ZIP.

The SG FoodID acquisition acquired all **2,689 foods**:
2,089 per 100 g and 600 per 100 ml, with 3,295 parsed portions. It includes local
hawker dishes such as steamed/roasted chicken rice and claypot chicken rice.

Archive SHA-256:
`bc686846eb0c81f4c3e231b222f7bb17a00010a474ccd0a2477f8cd1cecddafd`.

- Preserve g/ml bases separately; never equate volume and mass without density.
- Multiply displayed serving amounts by the supplied edible percentage. For
  steamed chicken rice, 346 g × 93.35% = 322.991 edible g; 151 kcal/100 g yields
  487.71641 kcal, consistent with the rounded source serving value of 488 kcal.
- In mapped nutrient cells, 6,636 `-` markers and 266 `Trace` markers remain unknown.
  Added sugar is separate from free sugar; free sugar is unknown for all records.
- Source-row retention includes original serving labels, values, edible percentage,
  source type (lab analysis/borrowed/derived/NIP), and update labels. There are no
  official record IDs in this mirror; internal source IDs hash its unique food names.
- A source-consistency check compared **22,598** supplied per-serving nutrient
  values against per-100 values scaled by edible quantity, allowing displayed
  rounding. One discrepancy remains: parsley energy, source 1 kcal versus computed
  0.324 kcal. It is retained in the food's import warnings, not silently corrected.
  This checks reconstruction, not independent food chemistry or clinical validity.
- No ingredient list, allergen safety, vegetarian classification, or meal suitability
  is inferred from dish names. Review annotations are separate from source import.

All 2,689 records were imported through application services into temporary
PostgreSQL and retrieved through the food API during verification. That database
was removed afterward; use `--import-records` to populate the configured deployment.

### FNDDS composition and portions

`ingestion.acquire("fndds", directory, 100)` downloads the official nutrient
and portion workbooks and translates their per-100 g edible nutrient values and
portion weights. The source contains **5,431 foods** and **22,046 portion rows**.
One nonpositive portion is omitted. The 100-record acquisition included 418 usable
portions and was verified through application services in temporary PostgreSQL.
It is a numerical benchmark/supporting catalogue, not a Singapore-representative
food pool. Missing free sugars and safety classifications remain unknown.

### Implementation boundaries

See [architecture](ARCHITECTURE.md#workflow-integration) for acquisition, adapter,
and database-import boundaries.

Normalize composition, portion, category, ingredient, and allergen records while
retaining source provenance. Reviewer corrections must remain traceable. Numeric
nutrient evaluation does not require an LLM call. Missing values are not zero;
total sugars are not interchangeable with free sugars. Catalogue coverage may not
support numerical evaluation of every guideline.

See [evidence](EVIDENCE.md) for guideline discovery, extraction, and publication;
see [inference](INFERENCE.md) for hosted-model budgeting.
