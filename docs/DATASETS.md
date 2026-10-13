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

## Dataset tools

```sh
.venv/bin/python -m backend.datasets.patients_generator --n 20 --seed 0 \
  --out "$CARELOOP_DATASET_DIR/fixtures/new_patients.json"
.venv/bin/python -m backend.datasets.source_acquisition
.venv/bin/python -m backend.datasets.research_transform
```

The generator defaults to the external patient fixture path, so use an explicit
new output if preserving the current snapshot. Research transformation requires
the optional `datasets` dependency group (`pandas`) and `pdftotext` for guideline
PDFs. Downloads may fail or require permission; a downloaded access page is not
the underlying dataset. Staging never writes live patients, publishes knowledge,
or fabricates approval coverage, diagnoses or observation dates.

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
