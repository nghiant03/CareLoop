# External datasets and code separation

The repository contains frontend code under `frontend/`, backend code under
`backend/`, and shared contracts/rule-engine/evaluation code in their existing
packages. **No raw datasets are bundled with code or Python distributions.**
`backend/datasets/` contains only location, generation, acquisition and staging
code. It is not a dataset directory.

## Local layout

Set `CARELOOP_DATASET_DIR` to an absolute path **outside the checkout**. The
default is `$XDG_DATA_HOME/careloop/datasets`, or
`~/.local/share/careloop/datasets` when XDG_DATA_HOME is absent:

```text
~/.local/share/careloop/datasets/
  fixtures/    dishes.json, patients.json, rules.json, example_trace.json
  research/    raw downloads, manifest, transformed research staging
  benchmarks/  preserved benchmark CSVs and accompanying reports
  legacy/      preserved clinical SQLite migration sources
  outputs/     new experimental results (unless CARELOOP_ARTIFACT_DIR is set)
```

Directories resolve without creation. Checkout-local roots and symlinks pointing
into the checkout are rejected. Missing inputs must be provisioned deliberately;
there is no bundled fallback or automatic download. Configuration changes require
a process restart because existing consumers cache their source paths/contents.

The local relocation was hash-verified. `relocation_manifest.json` records source
and destination paths and SHA-256 digests. Previously missing rulebook/example
fixtures were recovered into this external directory from commit `b58b685a`, not
restored into source control. They remain unreviewed development inputs.

## Development and testing

Provision the four fixture files from a separately maintained dataset snapshot,
then start the backend or run the existing tests:

```sh
export CARELOOP_DATASET_DIR="$HOME/.local/share/careloop/datasets"
.venv/bin/python -m pytest rules backend evaluation shared -q
```

A fresh checkout alone intentionally does not contain the dataset. Most existing
regression/evaluation tests need the external fixture snapshot; small path/schema
tests are self-contained. Python wheels and source distributions contain code
only. Frontend package/lock/TypeScript configuration JSON is code configuration,
not raw data, and remains tracked.

The fixture catalogue has 214 manually curated, unverified dishes; the patient
fixture is synthetic. These are distinct from public research participants and
from durable live clinical records. Published catalogue IDs and historical hash
keys remain unchanged. Keys such as `data/dishes.json` in persisted provenance
are historical logical identifiers, not current filesystem locations.

### Preserved catalogue semantics

Nutrients describe the recorded serving, not 100 g. All 214 fixture dishes remain
unverified estimates: 190 manual-curation records and 24 renal-replenishment
records. A new authoritative source must be reviewed rather than silently
overwriting historical dish IDs.

Nutrient tags use serving thresholds: `high_sodium` above 1000 mg,
`high_potassium` at least 700 mg, and `high_phosphorus` at least 300 mg.
`deep_fried` describes preparation or recorded fried components, not fat content;
`lean_protein` describes a substantive non-deep-fried fish, lean meat/poultry or
tofu component, not merely low saturated fat. These are curated recipe roles,
not clinically verified claims. Numeric limits and exclusions remain separate.

Synthetic lab arrays are newest-first; current potassium/phosphorus values equal
index 0. Generator output remains reproducible for a given seed and RNG backend.
Pregnancy and stage-5 archetypes remain excluded. The USDA gap filler remains a
rough equal-weight ingredient estimate; it does not establish clinical accuracy.

## Download research sources

Run from the repository root. Downloads stay outside the checkout:

```sh
export CARELOOP_DATASET_DIR="$HOME/.local/share/careloop/datasets"
.venv/bin/python -m backend.datasets.source_acquisition
```

The downloader reuses completed files and retries missing files. Interrupted
downloads use `.part` files and restart from the beginning, not from the last
byte. Keep the terminal open until it finishes. On completion,
`research/manifest.json` records each source URL, file size, SHA-256 hash and
download status. A successful command exit does not mean every source succeeded.
Check the manifest for `unavailable` entries before transforming data.

| Source | Downloaded content | Use |
| --- | --- | --- |
| [NHANES August 2021–August 2023](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?Cycle=2021-2023) | Nine SAS XPT files and HTML codebooks | Research demographics, measurements, dietary recalls and labs |
| [USDA FoodData Central](https://fdc.nal.usda.gov/download-datasets/) | Foundation Foods and FNDDS survey-food JSON ZIPs | Food composition candidates |
| [KDIGO 2024 CKD guideline](https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf) | Guideline PDF and index page | Unreviewed nutrition evidence |
| [MIMIC-IV demo 2.2](https://physionet.org/content/mimic-iv-demo/2.2/) | Public demo ZIP and index page | De-identified hospital research records |
| [Singapore meal study](https://pmc.ncbi.nlm.nih.gov/articles/PMC8304763/) | Article HTML | Published study tables, not participant-level data |
| [SG FoodID](https://www.hpb.gov.sg/healthy-living/food-and-beverage/sgfoodid/) | Access page only | Check bulk access and reuse permission separately |

NHANES files:

- `DEMO_L`: demographics.
- `BMX_L`: body measurements.
- `DR1IFF_L`, `DR2IFF_L`: individual foods from two dietary recall days.
- `DR1TOT_L`, `DR2TOT_L`: daily dietary totals.
- `BIOPRO_L`: standard biochemistry.
- `ALB_CR_L`: urine albumin and creatinine.
- `GHB_L`: glycated haemoglobin.

The downloader selects the latest matching USDA JSON links from its cached index.
The current index selects Foundation Foods **2026-04-30** and survey foods
**2024-10-31**. It does not download the branded-food archive. Keep the manifest
with the files to identify the releases used. Reruns reuse the index and archives,
so they do not automatically upgrade an existing snapshot.

Full MIMIC-IV requires PhysioNet credentials and its access requirements. The
downloader fetches only the public demo. It does not bypass access restrictions
or obtain SG FoodID bulk data. Check each source's license and citation terms
before reuse. A downloaded webpage is not the underlying dataset.

These research downloads do **not** provide the four CareLoop fixtures in
`fixtures/`. Use a matching, separately maintained CareLoop snapshot for development
tests and draft imports. The relocated fixtures already exist on this machine.
Do not replace them with NHANES participants or USDA records.

## Propose guideline-backed rules

```sh
.venv/bin/python -m backend.knowledge discover
```

This verifies the downloaded KDIGO PDF and automatically proposes protein and
sodium rule candidates with quotes, caveats and baseline-rule comparisons.
It requires `pdftotext` but not research transformation. Reports stay outside
the checkout. Candidates are unapproved and non-executable, with no database
writes. See [knowledge discovery](KNOWLEDGE.md#automatically-propose-evidence-backed-rules)
for supported recommendations, limitations and review steps.

## Transform research data

Install the optional dataset dependencies and ensure `pdftotext` is available
from your operating system's Poppler tools. Then run:

```sh
uv pip install --python .venv/bin/python -e '.[datasets]'
.venv/bin/python -m backend.datasets.research_transform
```

The transformer reads completed sources listed in the manifest. Missing downloads
are omitted, so inspect both the manifest and `research/staged/summary.json`.
Outputs include:

- `research/staged/research.sqlite3`: isolated research records and candidates.
- `research/staged/patient_candidates.jsonl`: NHANES research profiles.
- `research/staged/rule_evidence.jsonl`: unreviewed guideline extracts.
- `research/staged/singapore_study_tables.json`: extracted article tables.

USDA food candidates are stored in the staging database. They describe nutrients
per 100 g, not CareLoop serving portions. Missing nutrients remain null.
Successful reruns replace staging outputs. Preserve any outputs you need first.
If `research.build.sqlite3` remains after a failed run, inspect and move it aside
before retrying.

Staging never writes live patients or publishes rules. Review guideline exceptions,
units, portions, catalogue semantics and provenance before preparing a knowledge
draft. Use [the knowledge workflow](KNOWLEDGE.md) for reviewed publication.

## Generate synthetic patients

```sh
.venv/bin/python -m backend.datasets.patients_generator --n 20 --seed 0 \
  --out "$CARELOOP_DATASET_DIR/fixtures/new_patients.json"
```

Use a new output path to preserve the current snapshot. Without `--out`, the
generator writes to the external patient fixture path. Research staging never
fabricates approval coverage, diagnoses or observation dates.

## Database deployment

PostgreSQL clinical and knowledge journals remain separate from these files.
Production knowledge comes from one process-pinned published release, with no
fixture fallback. External fixture files can be explicit operator draft inputs,
but are not approvals. See [POSTGRES.md](POSTGRES.md).

Compose mounts the selected dataset directory read-only at `/datasets`; no seed
data enters the image build context. Set CARELOOP_DATASET_DIR explicitly when
using sudo, whose HOME may differ. Backend artifacts use the existing writable
artifact volume, not the dataset mount. Never expose real patient exports as
development seeds.

Raw data under legacy `data/`, `dataset/` or `datasets/` locations is ignored as
a defensive measure. Those locations must not contain code or tracked inputs.
