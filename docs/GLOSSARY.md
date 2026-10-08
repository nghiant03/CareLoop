# CareLoop domain glossary

Use these terms consistently across the rule engine, API, optimizer, frontend,
and evaluation code. Canonical serialized values live in
[`shared/envelope_schema.py`](../shared/envelope_schema.py); the broader data
flow is described in [ARCHITECTURE.md](ARCHITECTURE.md).

| Term | Meaning and important distinction |
|---|---|
| Nutrient envelope | Patient-specific daily nutrient constraints, exclusions, lifecycle status, patient snapshot, and evidence. It is not a meal plan. |
| Proposal | An envelope produced by a rule-engine run. Each run receives a fresh envelope ID; eligible proposals start PROPOSED, while scope exclusions or suppression can produce REJECTED envelopes. |
| Envelope version | Content revision within one envelope identity. An edit increments it; versions do not order separate proposals. Approval/rejection transitions do not increment it. |
| Lifecycle revision | Concurrency token within an envelope identity, incremented on every durable lifecycle update. Clients submit it as `expected_revision`; stale writes return `envelope_conflict`. |
| Scope eligibility | Proposal eligibility stored independently of status and notes. Clinician edits cannot clear scope exclusions or revive a rejected proposal. |
| Approval gate | The contract authorizing live downstream use only for APPROVED envelopes. EDITED means re-approval is required. Simulation copies are local evaluation inputs, not live approvals. |
| Hard constraint | A MAX daily ceiling or an exclusion. A violation makes a delivered plan infeasible. Nutrient names carry units, such as `sodium_mg` and `energy_kcal`. |
| Soft aim | A MIN floor or TARGET value. MIN measures shortfall; TARGET measures distance on either side. Missing a soft aim does not itself make a plan infeasible. |
| Feasibility | Satisfaction of hard constraints. A feasible plan can still miss nutritional aims. |
| Adequacy | Delivery against the original approved MIN/TARGET aims, reported separately from feasibility. |
| Relaxed constraint | A disclosed lowering of an unreachable soft MIN floor for the solver. It does not replace the original approved aim used for adequacy reporting. |
| Rule trace / `RuleFire` | Record of a fired rule, its priority, matched patient context, action summary, and citation. Superseded rules remain in the trace; firing does not imply winning a conflict. |
| Constraint provenance | Attribution for a specific constraint's kind, value, unit, envelope identity/version, and author. A guideline citation alone does not prove it authored a clinician-edited value. |
| Complete meal | In the composition optimizer, one main dish with an optional side, using heuristic catalogue roles. Distinct from a complete day of meal logging. |
| Complete logged day | Breakfast, lunch, and dinner have all been logged. This permits trend/soft-gap aggregation; partial-day hard violations remain visible. |
| Effective envelope | Historical approved snapshot selected for a logged date. Distinct from the latest proposed envelope, which may be unapproved. Dates without approval coverage remain unattributed. |
| Knowledge base (KB) | Versioned rule/dish graph and retrieval evidence, rebuilt in memory from repository data. Distinct from the durable application database containing clinical workflow state. |

External field names such as `serum_K_meq_L` and `serum_PO4_mg_dL` have established
aliases in the shared model. Preserve them or use an explicit compatibility
migration rather than a naming-only change.
