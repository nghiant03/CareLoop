# CareLoop — Canonical Schemas

Shared contract between all modules. Authors: Lane A (rules), Lane B (optimiser),
Lane C (data), Lane D (API/integration).

## NutrientEnvelope

The envelope is the clinical output that the rule engine proposes and a clinician
approves. Live planning and personal target guidance require approval;
informational reads may inspect other states. See the authoritative
[approval-gate contract](../docs/ARCHITECTURE.md#2-the-approval-gate-invariant),
including scope eligibility and nonempty-target requirements for planning.

## Files
- `envelope_schema.py` — Pydantic v2 models (the Python-level contract).
- `envelope_schema.json` — generated JSON Schema (cross-language / API contract).
- `export_schema.py` — run `.venv/bin/python -m shared.export_schema` from the
  repository root after model changes; `--check` verifies the committed mirror.

`version` counts clinician edits. `lifecycle_revision` advances on every stored
transition and supports optimistic concurrency. Lifecycle requests may send
`expected_revision`; this is optional for older clients, and used by the web UI.
`scope_eligible` is proposal-owned and cannot be changed by editing notes/targets.
