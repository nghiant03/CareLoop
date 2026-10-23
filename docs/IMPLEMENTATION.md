# Implementation status

As of 2026-10-23. Product requirements live in [REQUIREMENTS.md](REQUIREMENTS.md);
module and transaction boundaries live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Implemented

- PostgreSQL-backed immutable revisions, transactional audit history, demo-role
  guards, and checksum-verified migrations.
- Evidence discovery and URL/PDF/text acquisition, retained originals, page/heading
  passages, lexical retrieval, refresh comparisons, structured numeric conflict
  checks, review, explicit publication, and retirement. See [evidence](EVIDENCE.md).
- Manual/CSV patient entry, cited target proposals, missing-fact handling, clinician
  completion/approval, and reassessment. See [patients](PATIENTS.md).
- Versioned food catalogue and reviewer annotations; SG FoodID, FNDDS, and NHANES
  adapters. Source audits and temporary import results are in [data](DATA.md).
- Bounded multi-item planning, three objectives, independent checks, clinician
  approval, substitutions, and transactional invalidation. See [planning](PLANNING.md).
- Planned/independent intake, item and atomic whole-meal logging, immutable
  corrections, completeness, and target comparisons. See [logging](LOGGING.md).
- Checked substitution recommendations and a reproducible public-food retrieval
  pilot. Nearest-neighbour retrieval remains the default; see [mining](MINING.md).
- Connected `ui` workspaces for patients/targets, food review, planning, logging,
  and evidence. Docker/Nginx and Compose serve the UI on localhost port 5173.

No persistent deployment database has been seeded. Real-source verification used
temporary databases; raw downloads and reports remain outside Git.

## Visual style

Preserve the deep navy shell, blue selection, white working surfaces, cool slate
backgrounds, Public Sans, tabular measurement numerals, sentence-case labels,
modest corners, and bordered controls.

## Latest verification

- Backend: 73 tests passed on temporary PostgreSQL 16.2; Ruff and wheel build passed.
  One upstream Starlette/httpx deprecation warning remains.
- UI: five active contract/component tests, production build, and lint passed.
- Desktop/mobile browser checks covered generation, approval, whole-meal logging,
  day completion, and reviewer navigation without exceptions or horizontal overflow.
- Compose configuration, documentation links, packaged migrations, and whitespace
  checks passed. Temporary verification servers and databases were removed.
- Docker image execution and PostgreSQL 18 remain unverified due to socket permissions.

Commands: [backend](../README.md#verify), [UI](../ui/README.md#verify).
These checks are engineering verification, not clinical validation or the full evaluation.

## Unfinished work

- Broader NHANES demographic/clinical-field integration; only respondent ID and
  survey age are currently mapped.
- Reviewed public-food meal suitability and restriction coverage; missing nutrients
  also limit eligible planning pools.
- Hosted-model pilot, structured extraction, and cited chat. No provider credentials
  have been supplied; calls must fit Neuralwatt Basic's included allowance.
- Full frozen [evaluation](EVALUATION.md), including comparative search benchmarks
  and a reproducible unified command/report.
- Recipe preparation instructions.
- Docker deployment/PostgreSQL 18 verification and persistent deployment seeding.
- Old CareLoop Docker/database cleanup, described below.

## External cleanup blocker

The code/dataset reset is complete. Old project `careloop-app` resources have not
been confirmed removed: Docker socket access is unavailable and sudo requires a
password. Its databases were `careloop_clinical` and `careloop_knowledge`; declared
volumes were `postgres_data` and `run_artifacts`. Port 5433 connections also failed.
The current `careloop` project uses separate `database_v1` storage.

An operator with Docker access should inspect the exact old project resources
before removing them. The old Compose file was saved at
`/tmp/opencode/careloop-reset-compose.yaml`; if absent, recover it from Git history.

```sh
sudo docker compose -f /tmp/opencode/careloop-reset-compose.yaml --project-directory "$PWD" -p careloop-app ps -a
sudo docker volume ls --filter label=com.docker.compose.project=careloop-app
sudo docker compose -f /tmp/opencode/careloop-reset-compose.yaml --project-directory "$PWD" -p careloop-app down --volumes --remove-orphans
```

Do not prune global volumes or other projects, or reuse the old volumes.
