# Patient facts and target review

Implemented API contract, 2026-10-23. These are engineering choices for the initial
workflow, not a complete clinical schema. Interactive requests are available at
`/docs`; all mutations require a clinician demo actor and a reason.

## Records and facts

`POST /api/patients` creates a record with `body.display_name`, `body.facts`, and
`body.provenance`. Optional `external_namespace` and `external_id` form a unique
pair. `POST /api/patients/{id}/revisions` takes a full replacement body and an
`expected_revision`. It preserves all previous facts and provenance. Reads expose
current and historical records. All clinicians can access all patients.

| Fact | Meaning |
| --- | --- |
| `observed_on` | Known snapshot date, otherwise null |
| `age_years` | Observed age, 2–120; not automatically advanced over time |
| `sex` | `female`, `male`, or `other`, if recorded |
| `pregnant`, `breastfeeding`, `dialysis` | Explicit boolean or unknown |
| `weight_kg`, `height_cm` | Recorded measurements in kg/cm |
| `egfr` | Recorded eGFR in mL/min/1.73 m²; no diagnosis/stage inference |
| `has_ckd` | Explicit CKD status: true (Yes), false (No), or null (Unknown) |
| `ckd_stage` | `G1`, `G2`, `G3a`, `G3b`, `G4`, or `G5`, if recorded |
| `conditions`, `medications`, `allergies` | Exact, case-sensitive labels |
| `vegetarian`, `include_eggs`, `include_dairy` | Explicit dietary choices or unknown |
| `dislikes` | Soft preferences, distinct from allergies |

All fact fields are optional when entering records. Null is unknown; an empty list
means explicitly known absence. No defaults invent diagnoses or allergies. Age is
required to approve targets; recorded dialysis blocks approval as outside scope.
The editor shows CKD stage only for Yes; choosing No or Unknown clears the stage.
The API rejects No combined with a stage. Legacy stage-only records imply Yes
when validated or evaluated, without rewriting historical snapshots. A missing
status and missing stage remain Unknown; eGFR alone never establishes CKD.
One snapshot date is supported; independently dated observations, terminology
mapping, fact freshness policies, and ongoing age calculation remain future work.

Provenance records `kind` (`manual`, `csv`, or `public_dataset`), source, notes,
optional edition/record ID, and optional raw-source SHA-256. It is descriptive
provenance, not verification of a submitted clinician label.

## CSV import

`POST /api/patients/import-csv` accepts `{actor, reason, content}` where content is
CSV text with exactly these columns in order:

```text
display_name,external_namespace,external_id,facts_json,provenance_json
```

The last two columns contain JSON objects matching the API fields above. Use a
CSV writer to escape their quotes. Blank external fields mean no external ID; both
must be populated together. The import is create-only, at most 5,000 rows / 5 MB.
All rows validate before writes; any duplicate database identity rolls back the
whole import. Re-importing does not overwrite existing records. Correct records
through explicit patient revisions instead.

The public NHANES adapter produces this CSV contract; see [data acquisition](DATA.md).

## Rule applicability and calculations

Proposals use only published, non-retired revisions. Predicates are evaluated as:

- Applicability: **all** predicates must be true (empty means all patients).
- Exceptions: **any** true predicate excludes the rule (empty means no exceptions).
- A definite false applicability predicate or definite true exception excludes the
  rule without requiring unrelated missing facts. Otherwise, unknown applicability
  or exceptions produce incomplete results, with named missing facts.
- Numeric fields support `eq`, `gte`, and `lte`; boolean/text fields support `eq`;
  list fields support `contains`. Unsupported fields/types/operators block
  completion rather than becoming false. There is no arbitrary expression execution.
- Explicit `has_ckd=false` makes a CKD-stage predicate false without requiring a
  stage. This excludes stage-scoped applicability but does not trigger a stage
  exception. Yes/Unknown without a stage still requires clarification for stage
  predicates. Conflict analysis treats No CKD and required CKD stages as disjoint.
- Narrative population/exception notes are shown for clinician review. They are
  not executable predicates: reviewers must encode conditions explicitly before
  publication. Complex Boolean groups and unimplemented facts need rule revisions.

Numeric targets support energy (`kcal/day`), protein/carbohydrate/fat/saturated fat/
fibre/free sugars (`g/day`), and sodium/potassium/phosphorus (`mg/day`). Subjects use
the identifiers `energy`, `protein`, `carbohydrate`, `fat`, `saturated_fat`, `fibre`,
`free_sugars`, `sodium`, `potassium`, `phosphorus`.

A sourced protein recommendation in `g/kg/day` multiplies its explicit value(s)
by recorded `weight_kg` and preserves the calculation and original source action.
Missing weight prompts clarification. No energy formula, percentage conversion,
free-sugar substitution, or automatic reference-weight selection is implemented.
Recommended intakes, ceilings, and ranges remain distinct action kinds.

Qualitative exclusions/timing remain qualitative. Assessment requirements and
additional amounts require clinician completion; an additional amount is never
used as a total. Unsupported nutrient/units also prompt clinician completion.

## Proposal, completion, and approval

1. `POST /api/patients/{id}/targets` with `expected_patient_revision` generates an
   immutable evaluation of all current published rules and target revision 1.
   The response includes citations, eligibility, missing facts, and blockers.
2. `POST /api/targets/{id}/revisions` supplies `expected_revision`, `selected`
   rule/revision references, `manual` targets with rationale, and `dispositions`
   explaining omitted recommendations or completed assessment requirements.
3. Evidence-derived values are copied server-side. To alter one, deselect its
   rule, explain the disposition, and supply a manual target. Manual targets carry
   clinician authorship and rationale, not false source citations.
4. Missing facts and unsupported applicability predicates cannot be dismissed by
   a disposition. Correct the patient/rule and create a fresh proposal. Different
   numeric recommendations for one nutrient block approval until explicitly
   selected/replaced; the system never silently chooses the strictest value.
5. `POST /api/targets/{id}/approval` requires the exact revision and a
   `completeness_note`. There must be at least one completed target, no unresolved
   blockers, and a current patient/evidence snapshot. Completeness is a clinician
   attestation; the system does not claim universal clinical adequacy.

Approved targets cannot be edited. Create and approve a new proposal to replace
them. Approval supersedes prior approved sets; all remain readable.

## Reassessment and planning

Patient revisions conservatively flag all their current target sets for review.
Publication/retirement re-evaluates target patient snapshots and flags sets when
the relevant rule revision/status signature changes. This includes new rules and
rules that were previously inapplicable. Irrelevant publications and unpublished
draft edits do not invalidate targets. Manual targets also require review when
newly relevant evidence appears.

Evidence and patient/target mutations share a database transaction lock. Flags,
approvals, and audit entries commit together; concurrent approval cannot leave
stale targets ready. New proposals are allowed during reassessment because they
are how clinicians perform that reassessment.

`GET /api/patients/{id}/target-readiness` identifies a current approved target set.
This is **target readiness only**, not a meal-plan safety verdict. The planner adds
catalogue/allergen completeness, mandatory restrictions, independent checking,
and exact target-version binding. Plan invalidation now follows target changes;
see [planning](PLANNING.md). Existing values/history remain readable.
