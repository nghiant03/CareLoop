# CareLoop Mining

Knowledge-discovery modules over the synthetic CareLoop dataset
(`data/patients.json`, `data/dishes.json`). Pure-Python + numpy/scikit-learn,
no network access, fully deterministic.

Wired into the API by `backend/app/api/mining.py`:
`GET /mining/trends` (trend flags over the patient cohort) and
`GET /mining/substitutions?dish_id=...&k=...` (substitute dishes). Cohort
clustering is exposed as a library (`clustering.cluster_patients`), not as an
endpoint.

## Modules

### `clustering.cluster_patients(patients, k_range=(2, 6)) -> dict`

k-means cohort clustering. Retains candidate features present in at least one
patient (`age`, `bmi`, `hba1c_pct`, `egfr`, `serum_K_meq_L`,
`serum_PO4_mg_dL`, `systolic_bp`, `diastolic_bp`), drops wholly absent columns,
median-imputes missing entries, standardises, tries valid k values in the
inclusive range, and keeps the k
with the best mean silhouette (`random_state=42`, `n_init=10`).

Returns `{"k", "labels", "silhouette", "profiles", "feature_names"}` where
each profile has `size`, `means` (original units, 3 d.p.) and
`dominant_diagnoses` (top 3 by frequency).

### `substitutions`

- `load_dishes()` — cached loader for `data/dishes.json`.
- `nutrient_distance(dish_a, dish_b)` — v1: Euclidean distance over the 6
  core nutrients (`energy_kcal`, `protein_g`, `sodium_mg`, `potassium_mg`,
  `phosphorus_mg`, `carbs_g`), each min-max normalised across the whole dish
  DB (range `[0, √6]`).
- `suggest_substitutions(dish_id, k=3, version=2)` — v2 ranking:
  nutrient distance − category bonus (0.10 exact / 0.05 related) − cuisine
  bonus (0.03) − hpb_id/verified tiebreak (0.01 each), plus a
  healthier-choice prior (`0.20 ×` mean normalised sodium/potassium/phosphorus)
  applied **only to near-distance candidates** (within 0.25 of the best), so
  it nudges between similar dishes without re-ranking everything.

Category compatibility (this is what prevents "a soup for a drink"):
`hawker↔cai_png`, `zi_char↔soup`, `kopitiam↔drink↔dessert`, `healthy` alone.
The query dish is always excluded; results carry
`{dish_id, name, distance, nutrient_distance, category_match, reason}` sorted
by `distance` ascending.

> Dataset note: all 214 dishes currently have `hpb_id=None` and
> `verified=False`, so those tiebreaks are no-ops on today's data but are
> honoured for future verified dishes.

### `trends.detect_trends(patients) -> list[dict]`

Robust longitudinal slope (Theil–Sen: median of pairwise slopes) over dated
observations when present, otherwise `labs_K_monthly` / `labs_PO4_monthly`.
Dated observations use elapsed time rather than fixed monthly spacing; sparse
dated series can still flag an urgent latest value.

**Series orientation (important):** the brief assumed oldest→newest, but the
data is the opposite — for every patient `labs_*_monthly[0]` equals the
current serum value and `months_offset_ago == [0, 1, 2, 3, 4, 5]`, i.e. the
arrays are stored **newest-first**. `_oldest_first()` restores chronological
order using `months_offset_ago` when present (ascending-from-0 ⇒ reverse;
descending-to-0 ⇒ keep), falling back to matching the current serum value
against the first/last element, and defaulting to newest-first. Returned
`values` are always oldest→newest, so `values[-1]` is "now".

Flag rules: K+ slope > 0.05 mmol/L/month or 3-month projection crossing
5.5 mmol/L; PO4 slope > 0.05 mg/dL/month or projection crossing 5.0 mg/dL.
`severity` is `"urgent"` when the latest value already exceeds the alert
level (K+ ≥ 5.0, PO4 ≥ 4.6) or the projection crosses the threshold;
otherwise `"review"`. Output is sorted urgent-first, then by slope.

EWMA (half-life 2 months) can de-escalate urgent trends that have plateaued,
but not an urgent latest dated observation. Each flag: `{patient_id, analyte,
slope_per_month, ewma_slope_per_month, values, projected_3mo, severity, reason}`.

## Tests

```bash
# from the repo root
.venv/bin/python -m pytest backend/mining -q
```

`conftest.py` pins the repo root on `sys.path` so the package imports work
even without the editable install or the `pytest.ini_options` in the
repository-root `pyproject.toml`.
