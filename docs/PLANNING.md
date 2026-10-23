# Meal planning

Implementation choices, 2026-10-23. The planner assembles meals from recorded food
or dish portions. Each scheduled slot supports 1–5 distinct items; item counts are
configurable per slot. Recipe preparation/instructions remain future work.
Patient chat explains selected approved plans and retrieves checked substitution
suggestions through the same services. [Food mining](MINING.md) supplies
checked substitution recommendations. Reported intake
is supported through [meal logging](LOGGING.md).

See the [food catalogue](FOODS.md) for source adapters, units, and reviewer annotations.

## Mandatory checks

Patient allergies and vegetarian/egg/dairy choices must be explicitly recorded;
null prompts clarification. Allergy labels use the exact vocabulary in OpenAPI
(`egg`, `milk`, `peanut`, `tree_nut`, `soy`, `wheat`, `fish`, `shellfish`, `sesame`,
`gluten`, `sulphite`, `celery`, `mustard`, `lupin`, `mollusc`). Unknown labels block
planning; they are not silently normalized or ignored.

For each recorded allergy, the food must have an explicit `absent` classification.
Missing/unknown and `present` are excluded. Vegetarian requests require explicit
vegetarian suitability. Excluding eggs/dairy requires an explicit false
`contains_egg`/`contains_dairy` value. Dislikes remain soft ranking preferences.

Targets must be clinician-approved, current, and include an explicit daily energy
**range**. This is an initial planner contract, not an inferred calorie prescription.
Ranges and ceilings are mandatory daily bounds; recommended intakes are fit goals.
Unknown amounts for any targeted nutrient exclude that candidate. Qualitative
target actions that this planner cannot execute block the request rather than
being ignored. No automatic tolerance or blanket calorie deficit is invented.

## Generation and approval

`POST /api/plan-requests` accepts a patient actor, reason, exact target
ID/revision, start date, 1–7 days, unique schedule slots, and a selected pool of
1–100 food IDs. The default schedule is breakfast/lunch/dinner; add snack explicitly.

The deterministic beam search uses width 32 and at most 500 portion/scale choices
per slot. Portion multipliers are 0.5, 1, and 1.5. The three objectives weight
nutrient fit, dislike avoidance, and variety differently. Repeated foods across
days are penalized for variety. Alternatives can coincide when the pool is narrow;
three distinct solutions are not guaranteed. Search is bounded, not optimality-
certified or an evolutionary algorithm.

`items_per_slot` sets an exact item count for each specified scheduled slot, for
example `{"breakfast": 2, "lunch": 3, "dinner": 3}`. Omitted slots default to one
item.
Counts outside 1–5 or for unscheduled slots are rejected. The five-item maximum
is an explicit compute bound, not a nutrition recommendation. Every item comes
from the selected pool; any selected food can appear at any requested meal. A food appears
at most once within a meal; adjust its portion rather than duplicate it.

All positive finite source portions matching the food's g/ml nutrient basis are
available directly. Missing quantities are excluded; no serving-label conversion,
density assumption or separate portion approval is needed. Per-food meal-slot
restrictions have been removed. The patient's requested schedule is still enforced.

`beam-source-portions-v3` expands one item position at a time, retaining the best 32 partial
days. Interim nutrient scoring scales the day's goal by filled item positions;
this is a search heuristic, not a prescribed meal-energy distribution. The selected
pool must contain enough distinct eligible foods for each requested item count.
The exact item count, independent checker, and published constraints apply to all
alternatives. Multi-item search quality still needs comparative evaluation.

Stored `meals` remains a flat list of food items, keyed by `(day, slot, item)`;
group entries with matching day/slot to display a meal. `item` is 1-based and
defaults to 1 when omitted. Checks return both `meal_totals` and `daily_totals`.

An independent checker recomputes totals with Decimal arithmetic, checks complete
schedule coverage, portion units, restrictions, and each day's mandatory bounds.
Totals are decimal strings (or null), so displayed rounding does not hide a failed
bound. Search scoring is never used as the approval verdict.

Requests return either blockers/excluded-food reasons, checked drafts, or unmet
drafts with `search_failed` and `infeasibility_proven: false`. Having no eligible
food in the selected pool is not a claim about all possible foods.

`POST /api/plans/{id}/approval` requires a clinician actor and review note. It
re-checks current targets, current food revisions, and the plan itself in the same
transaction. Only one alternative per request can be selected. Unmet, stale, or
already-selected alternatives cannot be approved. Reads are available at
`GET /api/plans/{id}` and `GET /api/patients/{id}/plans`.

## Substitutions and reassessment

`POST /api/plans/{id}/substitutions` identifies day/slot/item, replacement food, reviewed
portion ID, and multiplier. It requires a current approved parent plan and creates
a separate checked draft. It never mutates the approved parent's meals. A violating
replacement remains an explicitly unmet draft and cannot be approved. Approving
a replacement supersedes its parent; competing stale replacement drafts cannot
subsequently be approved.

The item selector defaults to 1. Substitution changes exactly
one item and retains its siblings; the entire resulting plan is checked. Mining
recommendations use the same item selector. Logging can confirm/change/skip items
individually or atomically confirm/skip a whole meal.

Patient changes and relevant evidence changes flag bound plans through target
reassessment. New target approval supersedes plans bound to prior targets. Food
corrections flag every referencing plan. Newly recorded allergens identify affected
meals, including unknown food classifications. Historical plans and quantities
remain readable. Generation/substitution against stale targets waits for clinician
review; the corrected food catalogue can be used in fresh requests afterward.
