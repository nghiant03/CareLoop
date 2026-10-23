# Meal logging

Implemented API contract, 2026-10-23. Intake is patient-reported observation,
not a plan approval or a safety classification. The patient demo role records and
corrects it; clinicians have a read-only intake review workspace. Actor labels are
not authenticated identities.

## Entries

`POST /api/patients/{id}/meal-logs` accepts an actor, reason, `logged_on` date,
meal `slot`, optional 1-based `item` (default 1), and one of these statuses:

- `as_planned`: provide `plan_id`; copies the pinned planned food and quantity.
- `changed_quantity`: provide `plan_id` and `scale`, the absolute multiplier of
  the pinned portion (not a multiplier of the planned quantity).
- `replaced`: provide `plan_id`, `food_id`, `portion_id`, and `scale`.
- `skipped`: provide `plan_id`; consumed intake is explicitly zero.
- `independent`: omit `plan_id`; provide food, portion, and scale.

All entries accept an optional note. Planned entries must match the plan's patient,
date, scheduled slot, and item. Only previously approved plans can be logged, including
historical plans now flagged for review. Their original food snapshots are retained.
Replacements and independent entries use a snapshot of the current catalogue
revision. Any catalogue portion can be logged, including foods not annotated for
planning: recording consumption does not recommend that food or alter a plan.

One entry is permitted per patient/plan/date/slot/item. Duplicate submissions return 409;
multiple independent entries are supported. Independent entries are additive and
must not also be used to describe the same planned meal's replacement.

## Corrections and history

`POST /api/patients/{id}/meal-logs/{log_id}/revisions` accepts the full replacement
entry plus `expected_revision`. It preserves the date, plan, slot, and item, appends a
revision, and rejects stale edits. `GET` on the entry returns its revision history.
Every write is audited. Corrections do not overwrite historical food values.

## Daily summaries

`GET /api/patients/{id}/meal-log-days/{YYYY-MM-DD}` returns current entries,
`recorded_totals`, and explicit day completeness. Optional `plan_id` adds that
approved plan's scheduled slots, distinguishing unlogged from skipped meals.

Totals use Decimal arithmetic and the food's 100 g or 100 ml basis. Missing
nutrients propagate as null rather than zero. A day with no entries has unknown
totals; an explicitly skipped meal contributes zero. Totals describe recorded
intake only, not necessarily all food eaten that day.

`POST` to the day endpoint with actor, reason, and `complete` records the user's
declaration that the day is complete (or reopens it). This is separate from whether
every planned slot has been logged: a day may contain only independent entries.
Any subsequent entry or correction reopens the day. Completeness does not fill in
unlogged meals or unknown nutrient values, and is not a measure of adherence.

`POST /api/patients/{id}/meal-log-confirmations` accepts actor, reason, plan ID,
date, slot, and `as_planned` (default) or `skipped`. It records every item in the
meal atomically. If any item is already recorded, the entire batch returns 409
without saving partial entries; use item-level logging/correction for partial meals.

## Target comparisons

`GET /api/patients/{id}/meal-log-days/{YYYY-MM-DD}/target-comparison?target_id=...`
compares recorded totals with the selected set's approved revision, including its
authorship/citations. It requires a target set for the same patient and exposes a
review flag for stale targets. Historical approved values remain available.

Partial days are not labelled deficient for being below a range or intake goal.
An already-exceeded upper bound can be shown on a partial day. Unknown nutrients
remain unknown; unsupported qualitative/unit comparisons are explicitly labelled.
Completeness remains a user declaration. These are intake comparisons, not clinical
outcome assessments. The connected meal-log workspace presents these comparisons.
