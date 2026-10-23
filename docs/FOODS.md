# Food catalogue

Implementation choices, 2026-10-23. See [planning](PLANNING.md) for how reviewed
foods enter plans, and [data audits](DATA.md) for source coverage and measurements.

## Source integration

Food adapters support the supplied Kaggle SG FoodID mirror and USDA FNDDS
2021–2023. Imports are explicit, atomic CLI batches, not API startup side effects.
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

Reviewers explicitly assign:

- `meal_slots`: breakfast/lunch/dinner/snack suitability as an item in that meal.
- `planning_portions`: IDs of appropriate portions from the source list.
- Optional ingredient, vegetarian, egg/dairy, and allergen classifications.
- A supporting `review_note` whenever assigning these annotations.

Importing a dish called “vegetarian” does not assign a vegetarian classification.
Source descriptions are not ingredient lists. Source consistency discrepancies
are retained in `import_warnings`; reviewers should inspect/correct them when
annotating a food. Cross-contact practices are not established by composition data.
