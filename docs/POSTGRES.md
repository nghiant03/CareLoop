# PostgreSQL deployment

The root `compose.yaml` owns all services: PostgreSQL, schema migration,
knowledge operator CLI, backend and frontend. There is no separate PostgreSQL
Compose file. PostgreSQL stores clinical and knowledge state in separate
databases; SQLite runtime and import support have been removed. The derived
in-memory knowledge graph is unchanged.

## Start the database

From the repository root:

```sh
export CARELOOP_OPERATOR_UID=$(id -u)
export CARELOOP_OPERATOR_GID=$(id -g)
mkdir -p "${CARELOOP_DATASET_DIR:-$HOME/.local/share/careloop/datasets}/outputs/knowledge"
docker compose config --quiet
docker compose up -d --wait postgres
docker compose run --rm migrate
```

Use `sudo docker compose ...` if Docker socket access requires sudo; retain the
operator UID/GID variables explicitly when using sudo for operator exports.

`postgres` uses PostgreSQL 18 and a named volume mounted at
`/var/lib/postgresql`. It publishes only **127.0.0.1:5433**. The container network
uses `postgres:5432`. Authentication is disabled (`POSTGRES_HOST_AUTH_METHOD: trust`);
this local loopback-only configuration has no credentials, TLS, replication or HA.
The image runs bootstrap scripts only on an empty volume.

Bootstrap provisions a single `careloop_admin` role (the Compose
`POSTGRES_USER`) that owns both databases and is used for bootstrap, schema
migration and all runtime access; finer role separation is out of scope for
this local deployment.

The `migrate` service applies schema version 1 explicitly before the backend
starts. The backend checks the recorded domain/version and never performs DDL.
The migration role is intentionally powerful for this local setup; production
should provision narrower schema-owner/migration privileges.

## Existing storage

Existing PostgreSQL version-1 databases remain supported without rewriting data.
SQLite runtime/import/relocation commands are removed. Preserve old database and
WAL files; this version does not delete or convert them. See [STORAGE.md](STORAGE.md).

## Bootstrap knowledge when no authoring journal exists

Fixtures are **draft inputs**, not automatically approved evidence. Configure
knowledge credentials for the CLI on the host:

```sh
export CARELOOP_KNOWLEDGE_DATABASE_URL="postgresql://careloop_admin@127.0.0.1:5433/careloop_knowledge"
.venv/bin/python -m backend.knowledge import --draft-id bootstrap \
  --rules-file "$CARELOOP_DATASET_DIR/fixtures/rules.json" \
  --dishes-file "$CARELOOP_DATASET_DIR/fixtures/dishes.json" --actor AUTHOR
.venv/bin/python -m backend.knowledge show --draft-id bootstrap
```

The input files must exist. Supply real operator-attested identities and review
notes; do not copy example identities as approval. An independent reviewer label
must approve the exact revision before a publisher can create a release:

```sh
.venv/bin/python -m backend.knowledge review --draft-id bootstrap \
  --expected-revision 1 --actor REVIEWER --decision approve --note 'Actual review record'
.venv/bin/python -m backend.knowledge publish --draft-id bootstrap \
  --expected-revision 1 --actor PUBLISHER --release-id knowledge-2026-10 \
  --note 'Actual publication/change record'
```

Actor labels are still attestations, not authentication. Compilation and scope
checks do not establish clinical validity; the existing unverified catalogue and
missing source quotes remain disclosed. See [KNOWLEDGE.md](KNOWLEDGE.md).

After schema initialization and knowledge publication:

```sh
export CARELOOP_KNOWLEDGE_RELEASE=knowledge-2026-10
docker compose up --build -d
curl --fail http://127.0.0.1:8080/api/kb/stats
```

If using sudo, pass the release explicitly, for example
`sudo env CARELOOP_KNOWLEDGE_RELEASE=knowledge-2026-10 docker compose up --build -d`.
An absent/unknown release blocks backend startup. Check hashes, historical
approvals/logs and saved plans before accepting new writes.

## Backups and restoration

Named volumes are not backups. Take consistent logical dumps and copy them to
encrypted storage outside this machine. Stop application writers for coordinated
clinical/knowledge dumps; each pg_dump is otherwise independently consistent:

```sh
mkdir -m 700 artifacts/postgres-backup-YYYYMMDD
docker compose exec -T postgres pg_dump -U careloop_admin -Fc careloop_clinical \
  > artifacts/postgres-backup-YYYYMMDD/clinical.dump
docker compose exec -T postgres pg_dump -U careloop_admin -Fc careloop_knowledge \
  > artifacts/postgres-backup-YYYYMMDD/knowledge.dump
chmod 600 artifacts/postgres-backup-YYYYMMDD/*.dump
```

Check command exit statuses. Preserve roles/credential provisioning separately;
database dumps omit cluster-wide roles. Rehearse restores into **new databases**
with `createdb` and `pg_restore --exit-on-error`, then verify rows, hashes, roles,
historical approval coverage and workflows. Never restore over live data merely
to test a backup. Retain the SQLite sources as protected pre-cutover snapshots;
switching back to them after new PostgreSQL writes would lose those writes.

Stop with `docker compose stop` or `down`; **never use `down -v`** unless data
deletion is intended. If an older application Compose volume exists, retain it;
the new stack does not delete or merge it. If the old separate PostgreSQL stack
was started, inventory its volume before changing projects—this setup does not
adopt or overwrite another PostgreSQL data directory automatically.

## Verification and remaining limits

Unit tests cover approval policy and the PostgreSQL adapter. Persistence/API and
knowledge integration tests require PostgreSQL. Live server
regressions require an explicit administrator test URL and create/drop only
unique `careloop_test_*` databases:

```sh
CARELOOP_TEST_POSTGRES_URL="postgresql://careloop_admin@127.0.0.1:5433/postgres" \
  .venv/bin/python -m pytest backend/storage -q
```

Tests report skipped integration cases
when no URL is supplied; that is not a successful PostgreSQL integration run.
Runtime connections are pooled (default maximum 5 per URL/process) and writers
are conservatively serialized per domain with PostgreSQL advisory transaction
locks. No automatic ambiguous-commit retry is performed. Revisit lock granularity
and connection limits after contention measurements.

This is still a local, non-HA deployment without authenticated actors, restricted
CORS, automated backup retention or a clinical validation process. It must not
be exposed publicly or used for real clinical operations on that basis alone.
