# CareLoop — Canonical Schemas

Shared contract between all modules.

## NutrientEnvelope

The envelope is the clinical output that the rule engine proposes and a clinician
approves. Live planning and personal target guidance require approval;
informational reads may inspect other states. See the authoritative
[approval-gate contract](../docs/ARCHITECTURE.md#2-the-approval-gate-invariant),
including scope eligibility and nonempty-target requirements for planning.
