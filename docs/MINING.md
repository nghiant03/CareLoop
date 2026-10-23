# Food mining and substitution recommendations

Implemented pilot, 2026-10-23. Food composition drives similarity; no patient
behaviour is mined. The algorithms do not establish allergen safety or suitability.

## Recommendation API

`POST /api/plans/{id}/substitution-recommendations` takes an actor/reason, `day`,
`slot`, optional 1-based `item` (default 1), and an explicit pool of 1–100 unique
`food_ids`. Optional controls:

- `method`: `nearest` (default), `cluster`, or `same_category`.
- `clusters`: 1–8, default 4; only cluster retrieval uses the fitted assignments.
- `limit`: 1–20 distinct foods, default 5.

The patient or clinician role can request recommendations against a current,
clinician-approved plan and current approved targets. The original food is excluded
as a replacement. No silent catalogue-wide sample or automatic fallback is used.
The response includes pool revision IDs, model parameters/assignments, exclusions,
checked portion counts, and rejected portions with whole-plan violations.

Retrieval is followed by the planner's meal-slot, reviewed-portion, allergy,
vegetarian, egg/dairy, and target-nutrient completeness checks. Each eligible
portion at scales 0.5, 1, and 1.5 replaces the requested item and passes through
the independent whole-plan Decimal checker. At most 500 portion choices are
allowed; larger requests ask the caller to narrow the pool. Only passing choices
are recommended. An empty result is not proof of infeasibility.

Ranking minimizes normalized daily target deviation plus 0.25 for a dislike match,
plus Euclidean nutrient distance for the two nutrient-based methods. Range targets
use their midpoint; intake targets use their amount. Satisfied ceilings contribute
no fit incentive. Dislikes remain soft. Each food retains its best passing portion,
with deterministic identity/portion/scale tie-breaking. Scores are visible.

Results show item nutrient differences, quantity/unit, and checked daily totals.
Unknown differences stay null. The `substitution` selection can be submitted to
the existing substitution endpoint with actor/reason; this recomputes the draft
using current state. The clinician must still approve it. Retrieval itself does
not save drafts, mutate meals, or grant approval. Food edits between retrieval and
submission may change the newly checked draft and must be reviewed there.

## Similarity and clustering

`macro-energy-kmeans-v1` uses protein, carbohydrate, and fat per 100 kcal, scaled
by fixed reference amounts of 25 g, 25 g, and 100/9 g respectively. These are
similarity features, not clinical targets or a reconstruction of total energy.
Taking nutrient/energy ratios avoids assuming that 100 ml equals 100 g.

Foods need positive energy and all three macronutrients; unknowns are not imputed.
Numerically overflowing/extreme ratios are excluded. Very low-energy foods can
have unstable ratios: this feature design is preliminary and needs evaluation.
Sodium, potassium, phosphorus, and other targeted nutrients are checked against
the whole plan even though they are not similarity features.

Clustering uses sorted identities, deterministic farthest-first seeds, up to 30
Lloyd iterations, and stable tie-breaking. Identical profiles can yield fewer
clusters than requested. Model fitting includes the pinned source food and selected
current candidates. Cluster retrieval searches only the source's cluster; nearest
retrieval searches all feature-complete candidates. Same-category retrieval uses
exact source categories and can include incomplete similarity features if all
target checks still pass. Categories alone are not suitability evidence.

## Public-food retrieval pilot

Run from a normalized `careloop-data` food export, with explicit report output:

```sh
uv run python -m careloop.evaluate_foods \
  --input /path/to/normalized-foods.jsonl \
  --output ~/.local/share/careloop/public/evaluation/food-mining-pilot.json \
  --limit 300 --clusters 4 --top 5
```

The command validates food records, records the input checksum, selects the first
300 source identities ordered by SHA-256(identity), and saves parameters,
memberships, per-query recommendations, aggregate metrics, runtime, and environment.
Selection is deterministic. Queries are included in the fitted catalogue model;
this is a transductive retrieval pilot, not a held-out generalization benchmark.
Same-category baseline ordering uses source identity rather than nutrient distance.

### Observed SG FoodID result

Run on the downloaded version-1 mirror, 2026-10-23: 300 of 2,689 foods selected,
12 excluded from nutrient similarity because their feature vectors were unavailable.

| Method | Queries with results | Mean known distance | Same-category fraction | Retrieval seconds |
| --- | ---: | ---: | ---: | ---: |
| Cluster-assisted | 288/300 | 0.06140 | 11.11% | 0.118 |
| Direct nearest | 288/300 | 0.05794 | 11.18% | 0.162 |
| Same category | 278/300 | 0.28648 | 100% | 0.092 |

Cluster and nearest methods each returned 1,440 neighbours and exposed 284 distinct
foods. Same-category retrieval returned 1,022 neighbours, exposed 214 distinct
foods, and had 87 unavailable distances (excluded from its mean).

Clustering did not improve similarity or category agreement in this pilot, so
direct nearest search is the API default. Runtime differences on this small sample
are preliminary single-run observations. The low category agreement also shows
that similar macronutrients are a weak proxy for interchangeable dishes.

The report is stored outside Git at
`~/.local/share/careloop/public/evaluation/sgfoodid-mining-pilot.json`.
This raw-catalogue pilot does not assign safety/meal annotations or measure
patient-target changes, palatability, restriction compliance, cluster stability,
or clinical outcomes. API workflow tests separately exercise mandatory checks.
The full frozen evaluation in [EVALUATION.md](EVALUATION.md) remains pending.
