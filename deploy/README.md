# CareLoop local deployment

The root `compose.yaml` is the only stack. It runs PostgreSQL 18, a one-shot schema
setup task, FastAPI and the React frontend. Clinical and knowledge storage remain
separate PostgreSQL databases. Existing volumes and retired SQLite files are never
automatically deleted or imported.

## Start

Provision external datasets as described in [DATASETS.md](../docs/DATASETS.md), then:

```sh
docker compose up --build -d --wait
```

No separate migration, knowledge CLI, operator UID/GID or admin-account creation
step is needed. PostgreSQL becomes healthy, `setup` prepares/checks both schemas,
and only then may the backend start. Setup failure blocks the backend; application
startup never performs schema creation. Existing compatible data is preserved.

The default `review` mode serves the knowledge workspace at
**http://127.0.0.1:8080/knowledge-review**. No draft/revision settings or published
release are needed. The browser supports source discovery, draft creation/editing,
independent review and publication through `/api/knowledge/*`. Clinical routes are
disabled. Instructions for adding arbitrary sources and editing the external prompt
are in [KNOWLEDGE.md](../docs/KNOWLEDGE.md). No provider is selected yet, so live LLM
extraction reports its unconfigured state rather than falling back to static patterns.

After publishing a reviewed release:

```sh
CARELOOP_DEPLOYMENT_MODE=published \
CARELOOP_KNOWLEDGE_RELEASE=YOUR_REVIEWED_RELEASE_ID \
docker compose up --build -d --wait
```

Published mode uses the clinical app and refuses missing/unknown knowledge releases.
Publication never activates a release or hot-reloads runtime caches. To return to
the knowledge workspace, select review mode and unset the release. If using sudo,
pass the relevant environment explicitly with `sudo env ... docker compose ...`.

## Local access and state

- HTTP binds to **127.0.0.1:8080**, overridden by `CARELOOP_HTTP_PORT`.
- PostgreSQL binds to **127.0.0.1:5433** with passwordless trust. Fresh installations
  use the built-in `postgres` role, not a custom admin account. Any local user with
  network access to the port can connect. This is not suitable for public deployment.
- Existing volumes initialized as `careloop_admin` require
  `CARELOOP_DATABASE_USER=careloop_admin` for connections. No role/data conversion
  is attempted. PostgreSQL initialization scripts run only against an empty volume.
- The operator workspace has no login. Names are attestations, not authenticated
  identities. Mutation request tokens, same-origin checks and a local Host allowlist
  protect the browser surface; they are not authorization.
- `careloop-app_postgres_data` contains the durable databases. `run_artifacts` holds
  unpublished outputs. Dataset mounts remain read-only, outside the checkout.
- No backup feature, schedule or container is implemented.

```sh
docker compose logs --tail=100 postgres setup backend frontend
docker compose stop
```

`docker compose down` preserves volumes. **`down -v` deletes databases.** Do not
discard an existing volume merely because startup reports a role/schema mismatch.

## Images and limitations

The backend image includes Poppler for PDF-to-text extraction and runs as its
existing non-root service user. That container identity is not an operator/admin
account. The frontend builds with `npm ci` and serves the existing design through
nginx. Operator uploads are limited to 32 MiB; discovery uses temporary files and
returns a review-only report. Clinical/published proxy settings remain separate.

The build excludes datasets, databases, credentials and generated frontend output.
Never put real patient information in demo fixtures. PostgreSQL schema preparation
does not import fixtures, approve envelopes or populate knowledge drafts.

This is a local academic demo, not a clinical deployment: no TLS, authenticated
operators, high availability, automatic release rollout or measured multi-worker
throughput. The backend uses one worker; a long proxy timeout is not a background
job system. Python dependency ranges and image tags are not fully reproducible
release locks. See [POSTGRES.md](../docs/POSTGRES.md) for setup and test boundaries.
