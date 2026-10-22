# PostgreSQL deployment

The single root Compose stack owns PostgreSQL, automatic setup, backend and frontend.
Clinical and knowledge state use separate databases. The derived in-memory SQLite
knowledge graph is not durable storage and remains unchanged.

## Automatic setup

From the repository root:

```sh
docker compose up --build -d --wait
```

The sequence is PostgreSQL readiness → one-shot `setup` → backend readiness →
frontend. There is no manual migration command or knowledge operator CLI.
The setup task invokes `backend.storage.setup` with no command options. It applies
schema version 1 only to empty databases, checks compatible existing schemas,
and refuses unrelated/incomplete schemas. It never drops tables, recreates data,
imports fixtures, creates approvals or publishes knowledge. Its failure blocks
backend startup. A retry checks existing compatible schemas without resetting them.

The application itself only checks schema availability/domain/version; runtime
startup never creates tables. Future schema changes require a deliberate update
to deployment-managed SQL and compatibility checks, not automatic recreation.

## Local database access

PostgreSQL 18 stores both databases in the named volume mounted at
`/var/lib/postgresql`. Host access is **127.0.0.1:5433**; container access is
`postgres:5432`. Password authentication is disabled for this local demo
(`POSTGRES_HOST_AUTH_METHOD=trust`). Any local user able to reach that port can
connect. Do not expose it on a public interface.

Fresh installations use PostgreSQL's built-in **`postgres`** role. There is no
custom admin account, password, operator UID/GID configuration or role/group
provisioning workflow. PostgreSQL still requires a role name in a connection URL;
the built-in role is a database superuser, not an application login.

**Existing volumes are not rewritten.** If a volume was initialized with
`careloop_admin`, set `CARELOOP_DATABASE_USER=careloop_admin` before starting
Compose. This selects the existing role for connections; it does not create,
rename or delete roles. PostgreSQL image initialization scripts run only on empty
volumes, so changing image environment settings does not change an existing cluster.

No backup feature, schedule or service is included. Preserve existing volumes and
retired SQLite/WAL files. `docker compose stop` and `down` preserve volumes;
**`docker compose down -v` deletes databases**. Never reset a volume to fix a role
or schema mismatch.

## Bootstrap knowledge in the browser

The default deployment mode is `review`. Open
**http://127.0.0.1:8080/knowledge-review** without a preselected draft or release.
Use Create draft to upload rulebook and catalogue JSON, inspect the draft,
record an independent review and publish the exact reviewed revision.
Actor names are attestations, not authentication. Existing fixture inputs remain
unreviewed until deliberately assessed; compilation does not establish clinical validity.

Discovery accepts multiple guideline files and an editable prompt without hashes
or a source manifest. Its provider-neutral interface is implemented, but no LLM
provider is configured yet. See [KNOWLEDGE.md](KNOWLEDGE.md).

After publication, activate the chosen release explicitly:

```sh
CARELOOP_DEPLOYMENT_MODE=published \
CARELOOP_KNOWLEDGE_RELEASE=YOUR_REVIEWED_RELEASE_ID \
docker compose up --build -d --wait
```

Changing releases requires a controlled restart. Unknown/missing releases block
clinical startup with no fixture fallback. To return to the operator workspace,
select review mode and unset the release. The workspace never serves clinical routes.

## Verification and limits

Persistence/API/knowledge integration tests require an explicitly provisioned
`CARELOOP_TEST_POSTGRES_URL` with permission to create/drop disposable databases.
Root test fixtures remove deployment URLs and operate only on unique
`careloop_test_*` databases. Without that URL, integration cases skip; this does
not verify a PostgreSQL server. Never run standalone probes against deployment data.

Runtime connections are pooled (default maximum 5 per URL/process). Writes use
per-domain PostgreSQL advisory locks; ambiguous commits are not automatically
retried. This is not a measured multi-server throughput guarantee.

This setup has no authenticated operators, TLS, high availability or clinical
validation process. Passwordless shared database access is intentionally suitable
only for a trusted local demonstration.
