# CareLoop

CareLoop plans Singapore meals, tracks adherence, and answers nutrition questions
with citations for T2D, hypertension and CKD stages 3–4. Planning and personal
targets require an APPROVED nutrient envelope. This academic showcase defaults
to `CARELOOP_APPROVAL_MODE=auto`: eligible new proposals are auto-approved and
clearly marked **demo, not clinically reviewed**. Set `CARELOOP_APPROVAL_MODE=clinician`
to demonstrate manual review. Edits always invalidate approval in both modes.
Scope exclusions and hard planning limits apply in both modes.

Persistent clinical and knowledge storage is PostgreSQL-only. SQLite runtime
and import support have been removed; existing database files are not modified.

## Deploy locally

The root `compose.yaml` runs PostgreSQL 18, migrations, FastAPI and React.
Clinical and knowledge databases are separate. Knowledge releases require restart.

### 1. Prepare the environment

Requires Docker Compose, daemon access, Python 3.11+ and `uv`. From the repository root:

```sh
uv sync --extra dev

export CARELOOP_DATASET_DIR="$HOME/.local/share/careloop/datasets"
export CARELOOP_OPERATOR_UID=$(id -u)
export CARELOOP_OPERATOR_GID=$(id -g)
mkdir -p "$CARELOOP_DATASET_DIR/outputs/knowledge"
docker compose config --quiet
```

Provision datasets **outside the checkout** using
[the dataset guide](docs/DATASETS.md). None are bundled. Compose mounts them
read-only at `/datasets`.

For NHANES, USDA, KDIGO and MIMIC demo downloads, follow
[the research download instructions](docs/DATASETS.md#download-research-sources).
Research data does not replace CareLoop fixtures or approved knowledge.

Propose guideline-backed rules with `.venv/bin/python -m backend.knowledge discover`.
Candidates need review. See [knowledge discovery](docs/KNOWLEDGE.md#automatically-propose-evidence-backed-rules).

### 2. Initialize the databases

```sh
docker compose up -d --wait postgres
docker compose run --build --rm migrate
```

PostgreSQL: `127.0.0.1:5433`. Migrations create schemas, **not clinical data or
knowledge releases**. The backend checks schemas but never creates tables.

Before startup:

- **Existing state:** preserve PostgreSQL volumes/backups and any retired SQLite
  files. This version cannot open or import SQLite journals.
- **Knowledge:**
  [create, review and publish a draft](docs/POSTGRES.md#bootstrap-knowledge-when-no-authoring-journal-exists).
  Publication requires independent approval of the exact draft revision.

### 3. Start the application

Use your reviewed, published release ID:

```sh
export CARELOOP_KNOWLEDGE_RELEASE=YOUR_REVIEWED_RELEASE_ID
docker compose up --build -d --wait
docker compose ps

curl --fail http://127.0.0.1:8080/api/healthz
curl --fail http://127.0.0.1:8080/api/kb/stats
```

Open **http://127.0.0.1:8080**. Backend proxy: `/api`. API docs: `/api/docs`.
Override the HTTP port with `CARELOOP_HTTP_PORT`. Missing releases block startup
without fixture fallback. Health checks do not establish clinical readiness.

If Docker requires sudo, use `sudo docker compose`. Preserve startup settings:

```sh
sudo env CARELOOP_DATASET_DIR="$CARELOOP_DATASET_DIR" \
  CARELOOP_KNOWLEDGE_RELEASE="$CARELOOP_KNOWLEDGE_RELEASE" \
  docker compose up --build -d --wait
```

## Operate and preserve state

```sh
docker compose logs --tail=100 postgres migrate backend frontend
docker compose stop
```

`docker compose down` keeps volumes. **`down -v` deletes databases.**
Back up both databases and test restoration before accepting writes.
Restart the backend when changing knowledge releases.

See [PostgreSQL operations](docs/POSTGRES.md) and
[deployment configuration](deploy/README.md).

## Code and documentation

| Location | Responsibility |
| --- | --- |
| `frontend/` | Web interface and HTTP adapters |
| `backend/` | API, storage, knowledge, planning, adherence and dataset tooling |
| `shared/`, `rules/` | Canonical envelope contract and rule engine |
| `evaluation/` | Evaluation workflows and published report summaries |
| External `CARELOOP_DATASET_DIR` | Fixtures, research data and generated outputs |

- [Architecture and contracts](docs/ARCHITECTURE.md)
- [Knowledge authoring and publication](docs/KNOWLEDGE.md)
- [External datasets](docs/DATASETS.md) and [storage](docs/STORAGE.md)
- [Clinician guide](docs/user-guide-clinician.md) and [patient guide](docs/user-guide-patient.md)

Development requires external fixtures. Backend:
`.venv/bin/uvicorn backend.app.main:app --reload --port 8000`.
Frontend: `npm ci`, then `npm run dev` in `frontend/` (port 5173).

Verification commands:

```sh
.venv/bin/python -m pytest rules backend evaluation shared -q
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Python tests need external fixtures. Persistence/API/knowledge integration tests
need `CARELOOP_TEST_POSTGRES_URL` (an admin URL); they create and drop only uniquely
named disposable databases, never the configured deployment databases.
Skipped tests do not verify a live server.
