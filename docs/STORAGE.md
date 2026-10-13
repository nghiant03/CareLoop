# Runtime storage and published artifacts

CareLoop separates versioned inputs and published evidence from writable state.
This is a storage baseline, not a claim of deployment or clinical readiness.

| Category | Location | Version control |
|---|---|---|
| Rules, dish catalogue, synthetic patient fixtures | External `CARELOOP_DATASET_DIR/fixtures/` | Never bundle; provision separately |
| Reviewed benchmark/evaluation snapshots | Markdown summaries in source; raw results in external `benchmarks/` | Raw data untracked; publish summaries deliberately |
| Application database | `CARELOOP_APP_DB`; otherwise `$XDG_STATE_HOME/careloop/careloop_app.sqlite3` or `~/.local/state/careloop/careloop_app.sqlite3` | Never commit |
| Knowledge authoring journal | Operator-selected `CARELOOP_KNOWLEDGE_DB`; separate draft/review/publish storage | Never commit; see [KNOWLEDGE.md](KNOWLEDGE.md) |
| PostgreSQL clinical storage | `CARELOOP_APP_DATABASE_URL` or `_FILE`; default Compose database `careloop_clinical` | Runtime credentials ignored, never committed |
| PostgreSQL knowledge journal | `CARELOOP_KNOWLEDGE_DATABASE_URL` or `_FILE`; separate `careloop_knowledge` database | Runtime reads only; operator journal writes |
| New evaluation, optimizer and retrieval runs | External dataset `outputs/{evaluation,optim,retrieval}/`; override `CARELOOP_ARTIFACT_DIR` | Never commit |

Database paths resolve when used. Benchmark output constants resolve on module
import, so set environment variables before launching a run. Existing
`--out-dir` for evaluation and `write_results(path=...)` for retrieval remain
supported. For experiment isolation, give each run a distinct artifact root.
Mining comparisons write external `outputs/mining/COMPARISON.md` and
`comparison_results.json`; the committed historical report remains unchanged.
Experimental `spike_pymoo.py` also writes outside the checkout. See [DATASETS.md](DATASETS.md).

## PostgreSQL deployment and import

The single root `compose.yaml` now includes PostgreSQL, an explicit schema
migration service, knowledge operator tooling, backend and frontend. See
[POSTGRES.md](POSTGRES.md) and [deploy/README.md](../deploy/README.md).
This configuration never auto-imports a SQLite file or approves knowledge.

The legacy path settings above remain available for imports and fixture tests.
Do not set both a PostgreSQL URL and a SQLite path for the same domain. A bad
URL, inaccessible server or absent schema fails closed; no SQLite fallback is
attempted. URL-file secrets are loaded without printing credentials. Runtime
roles cannot migrate schemas; schema initialization needs the migration admin.

With source and target application writers stopped, use
`python -m backend.storage.migrate import-sqlite --component clinical --source ...
--writers-stopped`. Select the target using the corresponding DATABASE_URL_FILE
environment variable. Repeat separately for a real knowledge SQLite journal if
one exists. The import takes a read-only WAL-aware snapshot, checks integrity,
rejects unexpected tables/columns, refuses populated targets or repeat imports,
and compares every imported column by row-multiset hash before committing.
JSON payloads remain TEXT so stored snapshot/citation bytes and existing knowledge
hashes are preserved; this version does not introduce JSONB numeric reformatting.
Generated identity counters are restarted transactionally after preserved IDs.
Each database import is atomic; the pair of imports is not one transaction.

The PostgreSQL boundary keeps the prior conservative write serialization using
transaction-scoped advisory locks per domain. Reads proceed independently.
This supports networked application processes safely but is not proof of high
concurrent-write throughput. Pool limits apply per process/database connection
URL (`CARELOOP_DB_POOL_MAX_SIZE`, default 5); account for workers and operator
connections when sizing server connection limits. Finer-grained locks are a
separate optimization, not an assumed migration benefit.

SQLite backup/relocation instructions below apply only to legacy storage.
PostgreSQL backup and restore instructions are in POSTGRES.md.

## Existing checkout: preserve and relocate state

The old `data/careloop_app.sqlite3` was relocated to external dataset
`legacy/careloop_app.sqlite3` and is no longer tracked.
It is not a demo fixture. Historical commits still contain it; ignoring a file
does not remove it from history. Assess its contents before sharing repository
history. History rewriting requires a separate, coordinated decision.

1. Stop all CareLoop processes writing to the old database.
2. Make a snapshot using the migration command, not a raw file copy:

   ```sh
   .venv/bin/python -m backend.app.core.migrate_storage \
     --source data/careloop_app.sqlite3
   ```

   The destination defaults to `CARELOOP_APP_DB` if set, otherwise the user state
   path above. Use `--destination /absolute/private/path/careloop.sqlite3` to
   choose another path. The command includes committed WAL contents, checks
   SQLite integrity, refuses existing destinations (including symlinks), and
   keeps the source. It does not alter the schema or switch a running service.

3. Set `CARELOOP_APP_DB` to the reported destination before restarting. Verify
   existing approvals, traces, saved plans and meal logs through the UI/API.
4. Keep the source as a protected rollback copy until verification is complete.
   Once writes resume on the new database, rollback to the old copy would lose
   those writes; plan a fresh snapshot rather than casually switching back.

If an old checkout database exists and the new default does not, startup fails
with migration instructions instead of silently opening an empty database.
An explicit `CARELOOP_APP_DB` override can temporarily keep using the old path.
If both locations already exist, explicitly choose the intended authority;
CareLoop does not merge databases. A fresh checkout starts with an empty runtime
database and uses the versioned synthetic patients as read-only fixture inputs.

## Service deployment

Set absolute paths owned by a dedicated non-root service user, for example:

```sh
export CARELOOP_APP_DB=/var/lib/careloop/careloop_app.sqlite3
export CARELOOP_ARTIFACT_DIR=/var/lib/careloop/artifacts
umask 077
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Provision the private directory with mode `0700` for that user first; do not run
the application as root to create it. In containers, mount a persistent local
volume at `/var/lib/careloop`; do not store state in the image, checkout or an
ephemeral container layer. New application database files are created with mode
`0600`; existing files/directories keep their permissions and must be audited.
Startup initializes storage and refuses to serve on storage failures.

SQLite remains a single-host storage choice. Do not share this file between
replicas across hosts or use network filesystems without a separately validated
SQLite deployment. This work does not add authentication, authorization, TLS,
restricted CORS, encryption, retention enforcement or a clinical validation
process. Those remain prerequisites before handling real patient data.

## Backup and restore

Use `migrate_storage` to create a snapshot at a **new** backup destination. Store
backups outside the source repository and protect them like the live database.
Define a retention policy and encrypted backup destination operationally.

To restore, stop writers, copy the selected backup to a new database path with
the same command, set `CARELOOP_APP_DB` to that path, and restart. Verify workflow
records and approval coverage before allowing writes. Periodically rehearse a
restore in an isolated environment; an integrity check alone does not prove the
backup meets recovery objectives.

## Evaluation and publishing

```sh
.venv/bin/python -m evaluation.run --quick
.venv/bin/python -m backend.optim.benchmark
.venv/bin/python -m backend.app.chat.retrieval_bench
```

These write unpublished run outputs, not the committed reports. Q4 still reads
the published optimizer snapshots by default. `evaluation.run --rerun-benchmark`
generates and consumes fresh optimizer output under the selected artifact root;
the report records those paths. It forces a full benchmark, not smoke results.

Review source/data metadata and protocol before deliberately replacing a
published snapshot. Do not publish reduced-budget smoke runs as full evidence.
Raw run outputs may contain patient snapshots or traces; never commit or expose
them merely because a directory is called `artifacts`.
