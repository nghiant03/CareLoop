# Food catalogue

## Explicit missing-value estimates, 2026-10-24

At the user's explicit request, `careloop.foods.estimates` adds labelled demo
estimates to the imported SG FoodID catalogue. This is a separate revision step,
not a claim that the original dataset measured those values. The original source
cells and previous food revisions remain available. Known values are not replaced;
allergen/vegetarian classifications are not inferred. Other source namespaces are
excluded from this estimator.

Method `sgfoodid-estimates-v1`:

- Restore usable per-100 source trans-fat cells. The importer now maps trans fat
  too. Values exceeding recorded total fat stay unknown during import; the estimator
  records that rejected source value before estimating it from other foods.
- Missing fibre, sodium, trans fat and total sugars use a median of at least three
  non-estimated donors with the same g/ml basis: exact subcategory first, then food
  group, then the same-basis catalogue. Donor ranges/counts and a donor-list hash are
  recorded. Estimated values never become donor measurements. No g/ml density is
  assumed. These are low-confidence estimates, not analytical measurements.
- Missing free sugars use total sugars as a conservative upper-bound proxy, not
  an equivalence. This can over-count intrinsic fruit/milk sugars. If total sugars
  itself is estimated, the proxy is explicitly low confidence and is not a
  guaranteed upper bound.
- Fresh fruit and non-starchy leafy/non-leafy vegetables/mushrooms on a g basis
  receive estimated 100 g edible fruit/vegetable credit per 100 g. All other
  categories receive zero *credit*, not a claim of zero actual vegetable content.
  Mixed dishes, processed produce, juices and starchy roots require recipe evidence
  for more credit; arbitrary recipe percentages are not fabricated.

Methods, confidence, estimates, restored values and rejected raw cells are retained
as JSON in `source_details.careloop_estimates`, with a visible review note. Food and
plan screens disclose estimated composition. Plan checks expose `uses_estimates`,
`estimated_inputs` and `composition_basis`; a valid numerical check using estimates
does not establish compliance from measured composition.

Applied and read-back verified 2,689 food revisions: 1,491 restored trans-fat values;
estimates for 1,198 trans-fat, 370 fibre, 316 sodium and 325 total-sugar values, plus
2,689 free-sugar proxies and fruit/vegetable credits (167 whole-produce credits).
Thirty-three trans-fat source values exceeded recorded total fat and were rejected
as donors. The dataset-specific fallback used subcategories or food groups; no
catalogue-wide median was needed for this run. Re-running prepared zero revisions.

Audit: `~/.local/share/careloop/reviews/2026-10-24/food-estimates/` retains the original
catalogue, revision plan, events, summary and generation preview. Prepare/apply:

```sh
uv run python -m careloop.foods.estimates --output ~/.local/share/careloop/reviews/2026-10-24/food-estimates
uv run python -m careloop.foods.estimates --output ~/.local/share/careloop/reviews/2026-10-24/food-estimates --apply
```

The preview for `04a29a39` had 2,573 eligible foods and three one-day alternatives
passing the numerical checks using estimates; 116 foods remained excluded for
unknown saturated fat. Food data revisions are live. The updated checker, removed
egg/dairy preference gates and visible estimate labels require API/web deployment.

Implementation choices, 2026-10-23. See [planning](PLANNING.md) for how source
foods enter plans, and [data audits](DATA.md) for source coverage and measurements.

## Source integration

Food adapters support the supplied Kaggle SG FoodID mirror and USDA FNDDS
2021–2023. Imports use explicit, atomic function calls with caller-owned transactions.
No clinical recommendations or approvals are seeded. See
[architecture](ARCHITECTURE.md#workflow-integration) for acquisition, adapter, and
persistence boundaries, and [data](DATA.md) for source audits.

## Catalogue contract

`GET/POST /api/foods` lists/searches or creates foods. `GET /api/foods/{id}` includes
history. `POST /api/foods/{id}/revisions` requires a reviewer actor, reason, full
replacement body, and expected revision. Historical nutrients/portions are retained.

Nutrients have a `basis` of **100 g or 100 ml**; energy is kcal, minerals mg, and
other nutrients g. Portions carry exactly one of `grams` or `millilitres`, matching
that basis. There is no assumed density conversion. SG FoodID portions are adjusted
by the source edible percentage; raw serving labels and source rows remain visible.
Unknown/trace values are null, not zero. Total, added, and free sugars are separate.
Trans fat is a separate optional gram value; legacy snapshots without it remain
unknown. `food_groups.fruit_and_vegetables` records qualifying edible grams per
100 g or 100 ml of the food's basis. A value on a gram basis cannot exceed 100;
millilitre-basis contributions require independently documented mass, not assumed
density. Any non-null contribution, including zero, requires a reviewer note with
its source/recipe fraction and qualifying definition. Food names/categories do not
establish this value. These contributions participate in daily totals separately
from nutrients, with unknowns propagated throughout checking and logging.

Planning uses all recorded portions with a positive finite quantity matching the
nutrient basis, without separate portion enablement or per-food meal-slot labels.
The planner can place a selected food at any requested meal. Household labels alone
do not supply weights, and no density is inferred. All 3,295 acquired Singapore
portions across 2,689 foods pass these quantity/unit checks.

Reviewers can add ingredient, vegetarian, egg/dairy, and allergen classifications
with a supporting `review_note`. Legacy `meal_slots` and `planning_portions` keys
are accepted and discarded on input; saved historical snapshots are not rewritten.

Importing a dish called “vegetarian” does not assign a vegetarian classification.
Source descriptions are not ingredient lists. Source consistency discrepancies
are retained in `import_warnings`; reviewers should inspect/correct them when
annotating a food. Cross-contact practices are not established by composition data.
