# CareLoop

A local academic nutrition application with clinician-reviewed targets and plans.
Implementation has restarted from the agreed [requirements](docs/REQUIREMENTS.md).

**Available now:** PostgreSQL-backed evidence review/publication, manual and CSV
patient entry, cited target proposals, clinician completion/approval, reassessment,
and audit history. Versioned foods, checked planning alternatives, clinician plan
approval, and substitution drafts are also implemented. Source adapters cover
SG FoodID (the supplied Kaggle mirror), FNDDS, and NHANES. The connected frontend
supports these review workflows, multi-item planning, logging and evidence acquisition.
Hosted extraction/chat and the full public-data evaluation remain pending.

## Run

```sh
docker compose up --build -d
```

The migration service initializes a fresh `careloop` database before the API
starts. Open <http://localhost:5173> for the application,
<http://localhost:8000/docs> for the interactive API and
<http://localhost:8000/api/health> for readiness. Database access is on localhost
port 55432; the Compose password is a public local-demo value, not a secret.
The new project/volume is `careloop` / `database_v1`, separate from the old
`careloop-app` reset resources.

For local Python development (Python 3.12+ and `uv`):

```sh
uv sync --frozen
docker compose up -d db
export CARELOOP_DATABASE_URL='postgresql://careloop:local-demo-only@127.0.0.1:55432/careloop'
uv run python -m careloop.db
uv run uvicorn careloop.api:create_app --factory --reload
```

## Review workflow

Use `/docs` to submit each request with a reviewer demo actor and a reason:

1. `POST /api/evidence/sources`: submit source text, title, locator, and edition.
2. `POST /api/evidence/rules`: create a structured rule with a verbatim quote and
   source location. Record applicability, exceptions, and unresolved blockers.
3. `POST /api/evidence/approvals`: submit selected rule IDs and exact revisions.
4. `GET /api/evidence/catalogue`: inspect drafts and retained published rules,
   resolve conflicts, and obtain the reviewed `generation`.
5. `POST /api/evidence/publications`: submit approved selections, that generation,
   and the manual `conflict_review` note.
6. Create revisions or retire a rule using its expected latest revision.

Approval does not publish. Editing does not replace an existing published version.
No sources, rules, patients, or clinical recommendations are preloaded. Structured
numeric conflicts block publication; broader interpretation remains manual.
Hosted automatic extraction remains future work.

## Patient targets and public data

Use a clinician demo actor for the patient workflow:

1. Create a record at `POST /api/patients` or import CSV at
   `POST /api/patients/import-csv`.
2. Generate a proposal at `POST /api/patients/{id}/targets`.
3. Inspect missing facts/citations; complete or override targets through
   `POST /api/targets/{id}/revisions`.
4. Approve the exact revision at `POST /api/targets/{id}/approval`.

Patient/evidence changes flag affected targets without changing historical values.
See [patient contracts](docs/PATIENTS.md) for CSV columns, units, missing-fact
semantics, conflict resolution, and the target-readiness boundary.

Download real NHANES survey records and prepare 100 age-only profiles:

```sh
uv run --extra data careloop-data nhanes --limit 100
```

Raw data, normalized CSV, and a checksum/field-audit manifest are saved under
`~/.local/share/careloop/public/nhanes/2021-2023/`. To also import into the migrated
database selected by `CARELOOP_DATABASE_URL`:

```sh
uv run --extra data careloop-data nhanes --limit 100 --import-records --actor 'Demo clinician'
```

This does not create diagnoses or approvals. The adapter maps only respondent ID
and observed survey age; other facts remain unknown. Re-importing the same external
IDs fails atomically rather than overwriting records. See [source audit](docs/DATA.md).

## Singapore foods and planning

Download and normalize all 2,689 records from the supplied SG FoodID mirror:

```sh
uv run --extra data careloop-data sgfoodid --limit 0
```

Add `--import-records --actor 'Demo reviewer'` to import into the migrated database
configured by `CARELOOP_DATABASE_URL`. FNDDS uses the same command with `fndds` as
the source. Raw downloads and manifests stay under `~/.local/share/careloop/public/`.
The default limit is 100; zero selects all food records.

Review food portions, meal slots, and relevant restriction classifications through
the food API before requesting plans. `POST /api/plan-requests` creates three
checked alternatives; the clinician approves one through `/api/plans/{id}/approval`.
See [food contracts](docs/FOODS.md) and [planning](docs/PLANNING.md) for the bounded search,
nutrient requirements, substitutions, and reassessment behavior.

## Meal logging

Use `POST /api/patients/{id}/meal-logs` to confirm a planned meal, change its
quantity, record a replacement or skip, or add an independent food entry.
Daily recorded-intake summaries and completion declarations are available at
`/api/patients/{id}/meal-log-days/{YYYY-MM-DD}`. Entries retain food snapshots and
audited correction history. See [logging contracts](docs/LOGGING.md) and `/docs`
for request schemas.

## Substitution recommendations and food mining

`POST /api/plans/{id}/substitution-recommendations` retrieves nutritionally similar
foods from a selected pool, checks each replacement against the whole plan, and
returns ranked choices with nutrient differences. Submit a choice through the
existing substitution-draft workflow for clinician approval. Direct nearest-neighbour,
cluster-assisted, and same-category methods are available.

See [mining](docs/MINING.md) for API parameters, algorithm limits, and the reproducible
SG FoodID retrieval pilot (`uv run python -m careloop.evaluate_foods`).

## Multi-item meals and evidence acquisition

Plan requests accept `items_per_slot`, for example
`{"breakfast": 2, "lunch": 3, "dinner": 3}`. Returned food items carry a 1-based
`item` within each day/slot. Use that selector for substitutions, recommendations,
and logging. Whole-meal confirmation is available through
`POST /api/patients/{id}/meal-log-confirmations`.

Evidence discovery starts at `/api/evidence/discovery-seeds` and `/api/evidence/discover`.
`POST /api/evidence/source-imports` accepts approved-domain URLs or base64 PDFs;
optional page ranges support large guidelines. Originals and searchable passages
are retained. `/api/evidence/conflict-check` reports structured conflicts before
publication. See [evidence](docs/EVIDENCE.md) for limits and real-source verification.

## Verify

UI development and checks are documented in [ui/README.md](ui/README.md).

```sh
uv run ruff check src tests
uv run ruff format --check src tests
docker compose config --quiet
uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
```

The final command starts a temporary PostgreSQL 16.2 instance, runs the complete
suite, and removes its own storage. It requires supported `pgserver` binaries
(verified here on Linux x86-64), but no Docker access. To verify against the
Compose PostgreSQL 18 instance instead:

```sh
CARELOOP_TEST_DATABASE_URL='postgresql://careloop:local-demo-only@127.0.0.1:55432/careloop' uv run pytest -q
```

Database checks create and remove only uniquely named `check_*` schemas. Without
the test database variable, plain `uv run pytest` skips integration checks.

See [architecture](docs/ARCHITECTURE.md), [implementation status](docs/IMPLEMENTATION.md),
and the planned public-data [evaluation](docs/EVALUATION.md). These workflow checks
are engineering verification, not clinical validation or the final evaluation.
