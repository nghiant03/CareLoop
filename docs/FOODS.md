# Food catalogue

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
