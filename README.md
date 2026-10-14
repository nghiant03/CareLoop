# CareLoop

CareLoop plans Singapore meals, tracks adherence, and answers nutrition questions
with citations for T2D, hypertension and CKD stages 3–4. Planning and personal
targets require clinician approval of a nutrient envelope.

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
.venv/bin/python deploy/prepare_secrets.py
docker compose config --quiet
```

Credentials in ignored `.secrets/` are preserved. Never print or commit them.

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

PostgreSQL: `127.0.0.1:5433`. Migrations create schemas, **not clinical imports or
knowledge releases**. The backend checks schemas but never creates tables.

Before startup:

- **Existing clinical state:** stop source and target writers, then follow
  [the verified SQLite import procedure](docs/POSTGRES.md#import-the-selected-sqlite-clinical-source).
  Source: `$CARELOOP_DATASET_DIR/legacy/careloop_app.sqlite3`.
  Populated targets and repeat imports are refused. Keep source and verification report.
- **Knowledge:** import an existing authoring journal, or
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

Python tests need external fixtures. PostgreSQL integration tests need a test URL.
Skipped tests do not verify a live server.
