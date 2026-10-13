# Local PostgreSQL server (prepared, not activated)

This setup provides PostgreSQL 18 on this development machine. It does **not**
migrate CareLoop or make its SQLite storage code PostgreSQL-compatible. Existing
clinical and knowledge files remain unchanged. Do not put a PostgreSQL URL in
`CARELOOP_APP_DB` or `CARELOOP_KNOWLEDGE_DB`; they currently expect file paths.

## Start when ready

Docker Engine and Docker Compose are required. From the repository root, create
an ignored secret file. These commands refuse to replace an existing password:

```sh
mkdir -p .secrets
chmod 700 .secrets
(umask 077; set -C; openssl rand -hex 32 > .secrets/postgres_admin_password)
docker compose -f compose.postgres.yaml up -d
docker compose -f compose.postgres.yaml ps
```

The image is `postgres:18-bookworm`; minor updates within 18 are possible when
pulling. Pin an approved image digest when reproducibility becomes necessary.
The PostgreSQL 18 image uses a volume mounted at `/var/lib/postgresql`, not the
older `/var/lib/postgresql/data` mount convention.

The server listens on **127.0.0.1:5433** on the host, not its public interfaces.
Other hosts cannot connect through this binding. If a future backend runs in
the same Compose network, its endpoint is `postgres:5432`. Loopback access is
not TLS-encrypted; this is a local development setup, not a remote-access design.

Two empty databases are created:

| Database | Intended access |
| --- | --- |
| `careloop_clinical` | `careloop_app`: clinical workflow reads/writes |
| `careloop_knowledge` | `careloop_knowledge_reader`: runtime reads; `careloop_knowledge_operator`: authoring reads/inserts |

`careloop_admin` is the image's bootstrap **superuser**, reserved for local
administration and future migrations—not application connections. Ordinary roles
start without passwords, so network login is disabled until you assign them:

```sh
docker compose -f compose.postgres.yaml exec postgres psql -U careloop_admin -d postgres
```

At the psql prompt:

```text
\password careloop_app
\password careloop_knowledge_reader
\password careloop_knowledge_operator
\q
```

Use different passwords; keep credentials outside Git. The bootstrap image uses
local socket trust inside the container: Docker access grants administrative
power. Do not give untrusted users access to the Docker daemon.

Default table/sequence grants apply to future objects created by
`careloop_admin` in `public`. No application schema exists yet. The eventual
migration must explicitly verify grants, implement publication/approval
invariants, and decide whether narrower table-level permissions are needed.
Database roles do not authenticate clinicians or reviewers.

Initialization SQL runs **only on an empty data directory**. Changing the SQL or
secret file later does not update existing roles, databases, or passwords. Use
explicit SQL migrations and `\password` instead. If first initialization fails,
inspect logs and existing state; do not delete the volume to retry blindly.

## Stop without deleting data

```sh
docker compose -f compose.postgres.yaml stop
# Or remove containers/network while preserving the named volume:
docker compose -f compose.postgres.yaml down
```

The named volume persists independently of the checkout. **Do not use `down -v`**
unless you explicitly intend to delete all local PostgreSQL data.

## Logical backups and restore rehearsal

Choose a fresh private destination and stop application writers for a coordinated
clinical/knowledge backup. These commands are run from the repository root:

```sh
mkdir -m 700 artifacts/postgres-backup-YYYYMMDD
docker compose -f compose.postgres.yaml exec -T postgres \
  pg_dump -U careloop_admin -Fc careloop_clinical \
  > artifacts/postgres-backup-YYYYMMDD/clinical.dump
docker compose -f compose.postgres.yaml exec -T postgres \
  pg_dump -U careloop_admin -Fc careloop_knowledge \
  > artifacts/postgres-backup-YYYYMMDD/knowledge.dump
```

Each dump is a consistent snapshot of its database, not a single cross-database
snapshot. Verify command exit statuses and restrict dump file permissions with
`chmod 600`. Copy backups to encrypted storage outside this machine; ignored
`artifacts/` is not a backup service. Retain role/credential provisioning securely
as well—database dumps do not include cluster-wide roles.

Rehearse restoration into fresh databases, never over live data:

```sh
docker compose -f compose.postgres.yaml exec -T postgres \
  createdb -U careloop_admin careloop_clinical_restore
docker compose -f compose.postgres.yaml exec -T postgres \
  pg_restore -U careloop_admin --exit-on-error -d careloop_clinical_restore \
  < artifacts/postgres-backup-YYYYMMDD/clinical.dump
```

Use the corresponding knowledge dump in a separate restore database. Check
record counts, historical revisions, hashes, privileges and workflows after the
application migration. Treat restore databases as sensitive clinical storage.

## Limits and next step

This is one database server with no replica, automated backups, point-in-time
recovery, or failover. A sleeping development machine is not an always-on host.
It is appropriate for developing the PostgreSQL migration, not the previously
discussed multi-server production availability target.

Next comes an explicit storage-layer migration and verified data import. Nothing
in this Docker setup changes CareLoop's active database selection.

Reference: [official PostgreSQL image](https://hub.docker.com/_/postgres).
