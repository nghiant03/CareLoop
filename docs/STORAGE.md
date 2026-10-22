# Runtime storage and published artifacts

CareLoop uses **PostgreSQL only** for persistent clinical and knowledge state.
The two databases remain separate. Runtime verifies migrated schemas but never
creates tables. Compose's one-shot setup task prepares/checks both schemas before
the backend starts; there is no manual migration CLI. See [POSTGRES.md](POSTGRES.md).

| Category | Location | Version control |
|---|---|---|
| Rules, dishes, synthetic patients | External `CARELOOP_DATASET_DIR/fixtures/` | Provision separately; never bundle |
| Clinical state | `CARELOOP_APP_DATABASE_URL` | Never commit dumps |
| Knowledge authoring journal | `CARELOOP_KNOWLEDGE_DATABASE_URL` | Separate PostgreSQL database |
| Reviewed benchmark/evaluation snapshots | External `CARELOOP_DATASET_DIR/benchmarks/` (`EVALUATION.md`, `benchmark_results.{csv,md}`, `benchmark_wall_time.{csv,md}`, `COMPARISON.md`, `RETRIEVAL_BENCH.md`) | Provision separately; never commit reports or raw results into source control |
| New run outputs | External dataset `outputs/{evaluation,optim,retrieval,mining}/`; override `CARELOOP_ARTIFACT_DIR` | Never commit raw outputs or generated reports |


## Removed SQLite runtime and imports

`CARELOOP_APP_DB`, `CARELOOP_KNOWLEDGE_DB`, the knowledge operator CLI,
`backend.app.core.migrate_storage` and SQLite import commands
are no longer supported. Retired environment settings fail explicitly rather
than silently selecting an empty PostgreSQL database. No database files are
deleted, opened or converted by this change. Existing PostgreSQL version-1
databases remain compatible, including their unused `careloop_imports` metadata.

Preserve old SQLite files and their associated WAL files as protected archives.
This version offers no automated cutover from them; retain the older tooling
in a separate checkout if a separately planned migration is needed. Never
replace existing PostgreSQL state with an empty demo database.
Historical commits may still contain old database files; assess repository
history before sharing it. History rewriting is a separate decision.

The in-memory SQLite knowledge graph and offline research/graph experiments
are derived data, not persistent clinical or knowledge journals. They remain
unchanged.

## Transactions and test isolation

Clinical writes and knowledge authoring use transaction-scoped advisory locks
per domain, with pooled connections (`CARELOOP_DB_POOL_MAX_SIZE`, default 5 per
URL/process). Reads proceed independently. Lifecycle revision checks, snapshot
history, and citation JSON are preserved. There is no automatic retry of an
ambiguous commit. Lock granularity is not a throughput guarantee.

Set `CARELOOP_TEST_POSTGRES_URL` to a dedicated test server's administrator URL
to run persistence/API/knowledge integration tests. Root pytest fixtures strip
deployment URLs and create/drop only unique `careloop_test_*` databases. Without
the test URL those tests skip; adapter and policy unit tests still run. Skips
are not live-server verification. Never point standalone probes at live data.

## Evaluation and publishing

```sh
.venv/bin/python -m evaluation.run --quick
.venv/bin/python -m backend.optim.benchmark
.venv/bin/python -m backend.app.chat.retrieval_bench
```

Evaluation runs print results without creating report files. To export
`results.json` and `EVALUATION.md`, explicitly supply `--out-dir /external/run`.
Existing reports are left unchanged when no export is requested.

The optimizer and retrieval benchmark commands write unpublished outputs. Set
environment variables before launch because some output constants resolve on
import. Retrieval `write_results(path=...)` remains supported. Give each experiment
a distinct artifact root outside the checkout.

The benchmark evaluation reads published optimizer snapshots by default. `evaluation.run
--rerun-benchmark` generates and consumes a fresh full benchmark and records its
paths. Review metadata and protocols before publishing a replacement; reduced
smoke runs are not full evidence. Outputs may contain patient snapshots or traces
and must not be exposed merely because they are called artifacts.
