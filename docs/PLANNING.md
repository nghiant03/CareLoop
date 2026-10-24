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

User-authorized estimated food revisions are supported. Numerical checks use the
stored values and disclose `uses_estimates`, per-food `estimated_inputs` for required
nutrients, and `composition_basis`. The plan UI labels estimated composition;
passing a check with approximate data is not measured nutrient compliance.
See [food estimation methods](FOODS.md#explicit-missing-value-estimates-2026-10-24).

Patient allergies and vegetarian choice must be explicitly recorded;
null prompts clarification. Allergy labels use the exact vocabulary in OpenAPI
(`egg`, `milk`, `peanut`, `tree_nut`, `soy`, `wheat`, `fish`, `shellfish`, `sesame`,
`gluten`, `sulphite`, `celery`, `mustard`, `lupin`, `mollusc`). Unknown labels block
planning; they are not silently normalized or ignored.

For each recorded allergy, the food must have an explicit `absent` classification.
Missing/unknown and `present` are excluded. Vegetarian requests require explicit
vegetarian suitability. Egg/dairy inclusion preferences have been removed from
patient controls and planner checks. Legacy `include_eggs`/`include_dairy` values
do not gate generation, checking, approval or substitutions. Explicit egg/milk
allergies still use allergen classifications. Dislikes remain soft ranking preferences.

Targets must be clinician-approved, current, and include an explicit daily energy
**range**. This is an initial planner contract, not an inferred calorie prescription.
Ranges, ceilings and `minimum` actions are mandatory daily bounds; historical
`intake` actions remain soft reference/fit goals. `upper_exclusive=true` on a ceiling
means strictly less than; the default false preserves existing inclusive ceilings.
Unknown amounts for any targeted nutrient exclude that candidate. Qualitative
target actions that this planner cannot execute block the request rather than
being ignored. No automatic tolerance or blanket calorie deficit is invented.

### General and condition-specific constraints

`%energy` is supported for protein, carbohydrate, free sugars, total fat, saturated
fat and trans fat. Percentages use each day's actual total energy: grams × 4 kcal/g
for protein/carbohydrate/free sugars or × 9 kcal/g for fats, divided by daily kcal,
then ×100. Unknown nutrients/energy or nonpositive total energy cannot establish a
valid percentage. No fixed calorie assumption or automatic conversion to g/day is
made. Search uses partial-day ratios without scaling percentage limits by the number
of filled positions; absolute daily bounds are scaled only for ranking partial days.
Final checking always applies complete daily bounds with Decimal arithmetic.

Fruit/vegetable targets use `fruit_and_vegetables`, `g/day`, and reviewed edible
gram contributions per food basis (see [foods](FOODS.md)). Mixed dishes require a
documented qualifying recipe fraction; absent classifications remain unknown, not
zero. `trans_fat` has its own composition field; total fat never substitutes for it.
Existing datasets are not assumed complete for these fields or for free sugars.
Search excludes foods missing required values and explains why. Capability support
does not establish feasibility for the current food pool.

Search, final approval checks, substitutions, recommendation ranking and reported
intake comparisons share the same units and bound semantics. Minimums do not reward
arbitrarily exceeding the floor; ceilings do not reward eating up to the limit.
Same-unit incompatible minimum/ceiling and strict-equality conflicts block evidence
publication. Distinct targets for the same nutrient still require explicit clinician
resolution, including mixed absolute/percentage targets; no silent tightest-bound
selection is introduced.

## Generation and approval

`POST /api/plan-requests` accepts a patient actor, reason, exact target
ID/revision, start date, 1–7 days, and unique schedule slots. Omitted/null `food_ids`
searches all latest catalogue records, without the catalogue listing's pagination
limit. Optional `food_ids` restricts search to 1–100 selected foods; an explicit
empty list is invalid. Optional `excluded_food_ids` excludes up to 100 foods.
Duplicates and selected/excluded overlaps are rejected. The default schedule is
breakfast/lunch/dinner; add snack explicitly. Target approval does not generate plans.
Requests pin considered food IDs/revisions in `food_pool_revisions` for audit.

The deterministic beam search uses width 32 and at most 500 portion/scale choices
per slot. Portion multipliers are 0.5, 1, and 1.5. The three objectives weight
nutrient fit, dislike avoidance, and variety differently. Repeated foods across
days are penalized for variety. Alternatives can coincide when the pool is narrow;
three distinct solutions are not guaranteed. Search is bounded, not optimality-
certified or an evolutionary algorithm.

In catalogue mode, restrictions and required composition/portion checks run before
shortlisting. Pools above 500 portion choices per slot are ranked by partial-day
nutrient fit and dislikes, with deterministic identity tie-breaking. The best choice
per distinct food is retained first, then remaining portions, up to 500 choices.
Explicit custom pools retain the existing candidate-limit blocker. Outcomes report
pool and eligible-food counts, eligible/searched portion counts, and whether a
shortlist was used. Shortlisting can miss suitable combinations; final checks remain
mandatory and failed search does not establish infeasibility.

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

`beam-source-portions-v5` expands one item position at a time, retaining the best 32 partial
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

Substitution recommendations also default to the catalogue when `food_ids` is
omitted, with optional custom pools/exclusions and bounded automatic shortlisting.
Every suggested replacement passes the complete resulting-plan checker.

Patient changes and relevant evidence changes flag bound plans through target
reassessment. New target approval supersedes plans bound to prior targets. Food
corrections flag every referencing plan. Newly recorded allergens identify affected
meals, including unknown food classifications. Historical plans and quantities
remain readable. Generation/substitution against stale targets waits for clinician
review; the corrected food catalogue can be used in fresh requests afterward.
