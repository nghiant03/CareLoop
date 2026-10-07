# CareLoop — Canonical Schemas

Shared contract between all modules. Authors: Lane A (rules), Lane B (optimiser),
Lane C (data), Lane D (API/integration).

## NutrientEnvelope

The envelope is the clinical output that the rule engine proposes and a clinician
approves. Only APPROVED envelopes are visible to downstream optimisation, RAG, and
patient-facing views. This is the *approval gate* invariant.

## Files
- `envelope_schema.py` — Pydantic v2 models (the Python-level contract).
- `envelope_schema.json` — JSON Schema (cross-language / API contract).
