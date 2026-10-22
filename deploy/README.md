# CareLoop deployment configuration

The single root `compose.yaml` packages PostgreSQL, explicit schema migration,
knowledge authoring tools, backend and frontend. Clinical and knowledge storage
use separate PostgreSQL databases. SQLite durable runtime and import support
have been removed; derived in-memory graphs remain unchanged.

| File | Purpose |
| --- | --- |
| `../compose.yaml` | Complete local service stack and persistent PostgreSQL state |
| `backend/Dockerfile` | Install the Python distribution and run a non-root Uvicorn worker |
| `frontend/Dockerfile` | Build with the npm lock file, then serve static files using non-root nginx |
| `frontend/nginx.conf` | SPA routing, static asset caching, `/api` proxy and container health endpoint |
| `postgres/01-databases.sql` | Empty clinical/knowledge PostgreSQL databases owned by the admin role |

## Application stack

Follow [the PostgreSQL guide](../docs/POSTGRES.md) before starting the app.
From the repository root, start only the database, and initialize
schemas first:

```sh
mkdir -p "${CARELOOP_DATASET_DIR:-$HOME/.local/share/careloop/datasets}/outputs/knowledge"
docker compose config --quiet
docker compose up -d --wait postgres
docker compose run --rm migrate
```

Bootstrap/review/publish a knowledge draft. These actions are explicit; schema
migration alone does not add clinical data or authorize a knowledge release. Then:

```sh
export CARELOOP_KNOWLEDGE_RELEASE=YOUR_REVIEWED_RELEASE_ID
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/healthz
curl --fail http://127.0.0.1:8080/api/kb/stats
```

Open **http://127.0.0.1:8080**. Set `CARELOOP_HTTP_PORT` to change the host port.
Only the frontend is published, only on loopback; the backend is reachable
through `/api`. The proxy strips `/api`, matching the frontend's existing HTTP
contract. Its health endpoint checks nginx only; `/api/healthz` checks the backend.
Neither endpoint establishes clinical readiness.

Backend knowledge mode is explicitly `database` and requires a published release.
No fixture fallback is allowed. A single admin role owns both databases; runtime
role separation is out of scope for this local deployment.
The `knowledge` service is an opt-in CLI under the `tools` profile, not an editing
API. Its bind-mounted export workspace is external dataset `outputs/knowledge`; set
`CARELOOP_OPERATOR_UID/GID` to the invoking user's IDs before exports.

## Knowledge review workspace

Review mode serves a dedicated UI at `/knowledge-review` (the root redirects
there), without a published release. It includes searchable rules, evidence,
conditions/actions, authoring blockers, catalogue, provenance, hashes, revision
comparison and event history. Clinical routes, document editing and publication
remain disabled. All displayed documents are pinned to the selected revision;
restart with the new revision after an edit.

Review mode is a switch on the single deployment: set
`CARELOOP_DEPLOYMENT_MODE=review`, `CARELOOP_REVIEW_DRAFT` and
`CARELOOP_REVIEW_REVISION`, and leave `CARELOOP_KNOWLEDGE_RELEASE` empty.
Approving/rejecting decisions are recorded in the same deployment. From the
repository root, substituting an existing draft ID and its current revision:

```sh
CARELOOP_DEPLOYMENT_MODE=review CARELOOP_REVIEW_DRAFT=YOUR_DRAFT_ID \
  CARELOOP_REVIEW_REVISION=1 \
  docker compose up --build -d backend frontend
```

With sudo, pass those variables using `sudo env`.

Decisions require a reviewer name, rationale and confirmation of complete-revision
review. The server enforces an independent reviewer, the exact current revision,
an unpublished draft and a single decision per revision. A process-bound request
token protects the mutation against cross-origin form submissions. Names remain
attestations, not authentication; keep this local operator surface on loopback.
Recording a decision does not remove source blockers, publish, activate knowledge
or establish clinical validity. Publication remains a separate operator action.

## State and existing data

`careloop-app_postgres_data` holds both databases. The backend UID/GID **10001**
writes only unpublished artifacts into `careloop-app_run_artifacts` under
`/var/lib/careloop/artifacts`. Application code is read-only; temporary files use
`/tmp`. Only the migration service can initialize schema.

**The first database run creates empty storage.** It does not copy the checkout's
database or your existing user-state database. Synthetic patient fixtures remain
available through the existing patient API; they are not imported patient rows.
Verify the selected PostgreSQL clinical journal before accepting new writes.

The build context excludes local databases, credentials, caches and generated
frontend bundles. Datasets are mounted from outside the checkout, not included
in images. Never put real patient information into demo fixtures.

SQLite runtime and import support have been removed. Preserve existing files;
this version cannot open or convert them. PostgreSQL backup/restore guidance is
in [`docs/POSTGRES.md`](../docs/POSTGRES.md). No automatic import runs on startup.

`CARELOOP_APPROVAL_MODE=auto` is the academic demo default. Eligible new targets
are auto-approved, not clinically reviewed. Set it to `clinician` for a simulated
manual-review workflow. Edits require manual re-approval in both modes.

Stop containers without deleting state:

```sh
docker compose stop
# Or remove containers/network while keeping the volume:
docker compose down
```

**Do not use `docker compose down -v`** unless deletion of clinical state is
intentional. Named volumes are persistence, not backups. Store consistent
backups outside Docker and rehearse restoration.

## PostgreSQL operations

See [`docs/POSTGRES.md`](../docs/POSTGRES.md) for credentials, schema migrations,
data import, knowledge publication, backup and restore rehearsal.

```sh
docker compose logs postgres migrate backend frontend
```

Changing knowledge releases requires a controlled backend restart. PostgreSQL
URLs use `CARELOOP_APP_DATABASE_URL` and
`CARELOOP_KNOWLEDGE_DATABASE_URL`, not legacy SQLite path settings.

## Deployment limits

This is a local demonstration/migration-development setup, **not a production
clinical deployment**. The app still lacks authenticated actors and role-based
authorization, uses permissive CORS, and exposes API documentation through the
proxy. There is no TLS termination, automated backup schedule, HA/failover or
automated multi-host rollout. Do not change the loopback binding to a public interface
without a separate security/deployment design.

The backend uses one worker because plan generation is CPU-intensive and the
current runtime caches and conservative PostgreSQL write serialization are not
evidence of measured multi-server throughput.
The 300-second proxy timeout does not create background jobs or guarantee a plan
finishes within that time. Revisit resource limits and worker/job architecture
after workload measurement.

Frontend dependencies use `npm ci` and the existing lock file. Python dependencies
still use manifest version ranges; image tags can change within their major or
stable track. Pin approved image digests and introduce a Python dependency lock
before claiming reproducible production builds. Major PostgreSQL upgrades need
an explicit upgrade procedure, not just an image-tag edit.
