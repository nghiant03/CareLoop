# Database-managed knowledge

## PostgreSQL deployment

The root Compose stack selects a PostgreSQL published release. Configure
`CARELOOP_KNOWLEDGE_DATABASE_URL` or `CARELOOP_KNOWLEDGE_DATABASE_URL_FILE` for
runtime readers and operator commands, with separate credentials. Never also
set the legacy `CARELOOP_KNOWLEDGE_DB` path. Run schema migrations with the admin
role through `backend.storage.migrate init`, not the operator `init` command;
on PostgreSQL the latter only verifies an existing schema.

[POSTGRES.md](POSTGRES.md) is the deployment/bootstrap/import guide. Database
roles replace filesystem-only access controls on the journal. Runtime reads
use read-only transactions and a reader role; operator writes are append-only.
Privileged administrators can still bypass guards. Actor labels still do not
authenticate people or establish clinical validity.

The SQLite paths/commands below document legacy import sources and isolated
fixture development. In PostgreSQL deployment, select a URL-file secret instead
of a SQLite path, then use the same import/edit/review/publish commands. No
published release is fabricated when migrating from fixture files.

The operator CLI manages rules and the dish catalogue in a **separate PostgreSQL
authoring database** in deployment; SQLite journals remain supported as legacy
import sources and isolated fixture tests. Drafts never authorize runtime use. The service loads one
explicitly selected, reviewed, published release through read-only connections,
then pins its contents for the process lifetime.

External `fixtures/rules.json` and `fixtures/dishes.json` remain bootstrap and regression fixtures
outside Git. In database mode they are not the live source, fallback, or authoring
authority. The in-memory graph/BM25 index remains a derived read model, not the
authoring journal. The patient-workflow database remains separate.

## Security and governance boundary

This phase exposes **no knowledge-editing HTTP endpoints**. Give database write
access only to trusted operators, and read access to the service account.
`--actor` records an operator-attested identity; it is not authenticated. An
approving reviewer label must differ from all authors/editors of the draft,
including case/whitespace variants, but labels cannot prove independent people.
Use your existing identity/change-approval procedures around this CLI. It does
not supply role-based access control, electronic signatures, or tamper-proof
audit storage. Privileged filesystem users can bypass SQL triggers.

Every successful mutation appends an audit event in the same transaction as its
content/review/publication record. Existing rows cannot be updated or deleted
through ordinary SQL. Full draft revisions and released content are retained.
Edits append a revision; review belongs to exactly one revision and does not
carry forward. Publishing requires the latest revision's approving review.
Rejected revisions require a new edit/review cycle, not replacement of the
review record. Published drafts cannot be edited; clone a release to continue.

Validation checks supported DSL, identifiers, unique IDs, finite nonnegative
nutrients, required catalogue fields, rule compilation, and representative
scope/suppression cases. It is not clinical validation or a complete behavioural
regression suite. Import/review output discloses unverified dishes and missing
optional guideline quotes/URLs. Existing evidence is preserved without claiming
new verification. Review knowledge changes and run the relevant clinical safety
and evaluation checks before publishing or deploying them.

## Bootstrap without switching the live app

Provision a private directory owned by the operator. Substitute real identities
and reviewed release names; the commands below describe the workflow, not a
pre-approved release. Nothing runs automatically on application startup.

```sh
export CARELOOP_KNOWLEDGE_DB=/absolute/private/path/careloop_knowledge.sqlite3
umask 077
.venv/bin/python -m backend.knowledge init
.venv/bin/python -m backend.knowledge import \
  --draft-id bootstrap --rules-file "$CARELOOP_DATASET_DIR/fixtures/rules.json" \
  --dishes-file "$CARELOOP_DATASET_DIR/fixtures/dishes.json" --actor AUTHOR
.venv/bin/python -m backend.knowledge show --draft-id bootstrap
.venv/bin/python -m backend.knowledge review \
  --draft-id bootstrap --expected-revision 1 --actor REVIEWER \
  --decision approve --note 'Describe the actual review and known limitations'
.venv/bin/python -m backend.knowledge publish \
  --draft-id bootstrap --expected-revision 1 --release-id knowledge-2026-10 \
  --actor PUBLISHER --note 'Reference the approved change record'
```

`--db /absolute/path` before the subcommand overrides the environment variable.
Without either, the CLI defaults to `careloop_knowledge.sqlite3` beside the
default user-state application database. `init` creates private storage; other
commands require an initialized database and never silently create a missing
one. Initialization refuses an existing database containing application tables.
Import captures raw source-file SHA-256 hashes and preserves the original JSON
metadata, citations and dish provenance. Published hashes use canonical JSON,
so they are independent of whitespace or key ordering.

## Select the release for runtime

Stop the service before changing its knowledge configuration. Configure these
settings in the service environment, not only the author's shell:

```sh
export CARELOOP_KNOWLEDGE_MODE=database
export CARELOOP_KNOWLEDGE_DB=/absolute/private/path/careloop_knowledge.sqlite3
export CARELOOP_KNOWLEDGE_RELEASE=knowledge-2026-10
export CARELOOP_APP_DB=/absolute/private/path/careloop_app.sqlite3
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Database mode requires both a database and an explicit release ID. Supplying
either database/release setting without a mode also selects database mode; an
incomplete configuration fails. Missing databases/releases, drafts, checksum
failures, unsupported schemas/DSL and validation failures block startup. There
is no fallback to Git data and no implicit “latest release” selection. Changing
settings within a running process is rejected; restart all workers together.
Publishing alone does not activate the release or hot-reload any cache.

For local development and existing fixture tests, unset the database/release
settings and use `CARELOOP_KNOWLEDGE_MODE=fixtures` (the default when unconfigured).
Explicit file arguments to low-level loaders remain available for tests and
offline experiments; live default loaders use the selected release.

Verify `/kb/stats`: it reports `knowledge_release_id` and source hashes. Rule
proposals persist `knowledge_release_id` and `knowledge_source_hashes`; plan
documents persist the active catalogue/retrieval release and retain their
approved-envelope snapshot. A plan can therefore record a newer catalogue
release than the historical envelope's rule release without rewriting either.
Evaluation metadata records the active release and hashes. Use
`evaluation.run --rerun-benchmark` when evaluating a new release rather than
treating historical fixture benchmark snapshots as evidence for changed data.

## Author the next revision

```sh
.venv/bin/python -m backend.knowledge clone \
  --release-id knowledge-2026-10 --draft-id next --actor AUTHOR
.venv/bin/python -m backend.knowledge export \
  --draft-id next --out-dir "$CARELOOP_DATASET_DIR/outputs/knowledge-edit"
# Edit the exported rules.json/dishes.json, not the published database rows.
.venv/bin/python -m backend.knowledge edit \
  --draft-id next --expected-revision 1 --actor AUTHOR --note 'Explain changes' \
  --rules-file "$CARELOOP_DATASET_DIR/outputs/knowledge-edit/rules.json" \
  --dishes-file "$CARELOOP_DATASET_DIR/outputs/knowledge-edit/dishes.json"
.venv/bin/python -m backend.knowledge history --draft-id next
```

Export refuses an existing output directory. `export --draft-id next --revision 1`
retrieves an earlier draft snapshot; `export --release-id ...` retrieves an
immutable release. `list` shows current revision, review, release and validation
information. Edits, reviews and publication require `--expected-revision` and
reject stale versions. Review revision 2 after the edit above; approving revision
1 would not authorize its publication. Assign a new release ID on publication.

**Dish IDs preserve historical clinical meaning.** A new release must retain all
previously published dish IDs with their nutrient values, portion, category,
ingredients and tags unchanged. Corrections get a new dish ID while retaining
the old record for saved plans and meal logs. Names and provenance/verification
metadata can be reviewed separately, but setting `verified=true` remains an
operator attestation requiring source evidence. There is no catalogue deletion
or deactivation mechanism in this phase; introducing one requires a separate
historical-log/saved-plan compatibility design.

## Backups, rollout and rollback

Back up both the knowledge journal and patient journal using consistent SQLite
snapshots (see [STORAGE.md](STORAGE.md)). Do not copy only an active database file
and omit its WAL. Store backups privately outside Git; rehearse restoration.
These snapshot instructions apply to SQLite sources. PostgreSQL logical
backup/restore and deployment limits are documented in POSTGRES.md.

First rehearse bootstrap and the chosen release against copies of application
state, verifying scope exclusions, target approval gates, citations, plan
feasibility/adequacy and historical logs. Selecting a release does not approve
patient envelopes or backfill provenance into old ones. Legacy envelopes remain
readable with a null release ID and empty knowledge hashes; their embedded
traces remain authoritative.

The envelope JSON Schema now includes optional provenance fields. Older backend
binaries with `extra='forbid'` cannot read newly written envelopes containing
those fields. Deploy compatible readers before new writes; a code rollback to
such binaries requires an appropriate state snapshot, not just a release switch.
Do not erase provenance from stored clinical records to work around that limit.

To roll knowledge back, stop workers, select the previous immutable release ID,
and restart with compatible code. Older catalogues may not contain new dish IDs
already referenced by live records; check those references and rehearse against
current state before rolling back. A release switch alone cannot guarantee
safe clinical rollback or recover writes made after a database backup.
