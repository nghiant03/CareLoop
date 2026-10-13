# CareLoop deployment configuration

This directory packages the **current** backend and frontend for a local,
single-host deployment. It also contains an independent PostgreSQL preparation
configuration. These are different stacks: the application still uses SQLite.

| File | Purpose |
| --- | --- |
| `../compose.yaml` | Backend, frontend/reverse proxy and persistent clinical state |
| `backend/Dockerfile` | Install the Python distribution and run a non-root Uvicorn worker |
| `frontend/Dockerfile` | Build with the npm lock file, then serve static files using non-root nginx |
| `frontend/nginx.conf` | SPA routing, static asset caching, `/api` proxy and container health endpoint |
| `../compose.postgres.yaml` | Independent, optional local PostgreSQL server |
| `postgres/01-databases.sql` | Empty clinical/knowledge PostgreSQL databases and access roles |

## Application stack

From the repository root, when you are ready to build and start services:

```sh
docker compose config --quiet
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

The application stack does not require PostgreSQL secrets or credentials.
Knowledge mode is explicitly `fixtures`, using the versioned synthetic patients,
rules and catalogue bundled with the Python distribution. See
[`docs/KNOWLEDGE.md`](../docs/KNOWLEDGE.md) before configuring a reviewed knowledge
database/release; this stack does not import or publish one automatically.

## State and existing data

`careloop-app_clinical_data` is a named volume mounted at `/var/lib/careloop`,
owned by backend UID/GID **10001** on initial creation. Clinical state is written
to `careloop_app.sqlite3`; run artifacts live under `artifacts/` in that volume.
Application code is read-only and temporary files use `/tmp`.

**The first run creates new, empty clinical storage.** It does not copy the
checkout's database or your existing user-state database. Synthetic patient
fixtures remain visible even before new clinical records are written. Container
data therefore does not represent a migration of existing patient state.

The build context excludes local databases, credentials, caches and generated
frontend bundles. Only the two explicit fixture JSON files under `data/` are
included. Never put real patient information into those versioned fixtures.

Before importing existing state, stop all writers and follow the integrity-
checked SQLite backup/migration procedure in
[`docs/STORAGE.md`](../docs/STORAGE.md). Provision the destination volume with
UID/GID 10001 ownership and private file permissions. Do not overwrite a populated
volume or copy an active SQLite file without its WAL. Keep a verified source
backup; this configuration deliberately performs no automatic import.

Stop containers without deleting state:

```sh
docker compose stop
# Or remove containers/network while keeping the volume:
docker compose down
```

**Do not use `docker compose down -v`** unless deletion of clinical state is
intentional. Named volumes are persistence, not backups. Store consistent
backups outside Docker and rehearse restoration.

## PostgreSQL preparation

See [`docs/POSTGRES_LOCAL.md`](../docs/POSTGRES_LOCAL.md) for secret creation,
startup and backup instructions for the separate PostgreSQL stack:

```sh
docker compose -f compose.postgres.yaml config --quiet
```

Starting that stack does not connect CareLoop to PostgreSQL. The required
storage-layer/schema/data migration has not been implemented; do not replace
SQLite path settings with PostgreSQL URLs.

## Deployment limits

This is a local demonstration/migration-development setup, **not a production
clinical deployment**. The app still lacks authenticated actors and role-based
authorization, uses permissive CORS, and exposes API documentation through the
proxy. There is no TLS termination, automated backup schedule, HA/failover or
multi-host database. Do not change the loopback binding to a public interface
without a separate security/deployment design.

The backend uses one worker because plan generation is CPU-intensive and the
current runtime caches/SQLite design are not a multi-server deployment solution.
The 300-second proxy timeout does not create background jobs or guarantee a plan
finishes within that time. Revisit resource limits and worker/job architecture
after workload measurement.

Frontend dependencies use `npm ci` and the existing lock file. Python dependencies
still use manifest version ranges; image tags can change within their major or
stable track. Pin approved image digests and introduce a Python dependency lock
before claiming reproducible production builds. Major PostgreSQL upgrades need
an explicit upgrade procedure, not just an image-tag edit.
