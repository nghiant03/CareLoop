# CareLoop — Data Layer (Lane C: Data & Mining)

Week 1 deliverables for the data & mining workstream: a curated Singapore dish
nutrient table, a deterministic synthetic patient generator, and a USDA
FoodData Central gap-filler skeleton for potassium/phosphorus.

## Contents

| File | Purpose |
|---|---|
| `dishes.json` | 190 curated Singapore dish records (energy, protein, Na, K, P, carbs, fat, sat fat, fibre, sugar). |
| `patient.py` | Pydantic `Patient` model — extends the canonical `shared.envelope_schema.PatientSummary` with archetype, vitals, and longitudinal labs. |
| `patients_generator.py` | Deterministic generator for N synthetic patients from 9 clinical archetypes. |
| `patients.json` | Generated output (default 20 patients, seed 0). |
| `usda_fill_gaps.py` | Skeleton: estimate missing K/P from USDA FDC by ingredient. |

## Dish data (`dishes.json`)

190 records across 8 categories: `hawker` (60), `zi_char` (30), `kopitiam` (28),
`cai_png` (25), `drink` (19), `soup` (16), `healthy` (6), `dessert` (6).

Each record:

```json
{
  "dish_id": "SG0001", "name": "Chicken Rice (Hainanese)",
  "category": "hawker", "tags": ["hawker", "chinese", "high_sodium"],
  "portion_g": 400, "energy_kcal": 600, "protein_g": 30,
  "sodium_mg": 1200, "potassium_mg": 500, "phosphorus_mg": 300,
  "carbs_g": 75, "fat_g": 18, "sat_fat_g": 5, "fiber_g": 2, "sugar_g": 3,
  "ingredients": ["chicken", "jasmine rice", "..."], "cuisine": "chinese",
  "hpb_id": null, "usda_match": null,
  "provenance": "manual_curation", "verified": false
}
```

### Tags

Tags are auto-derived where they encode a hard, checkable property, so they can be
trusted as rule inputs:

- `high_sodium` — sodium > 1000 mg/serving.
- `deep_fried` — fat > 20 g/serving.
- `lean_protein` — saturated fat < 3 g/serving.
- `high_potassium` — potassium ≥ 700 mg/serving (CKD caution).
- `high_phosphorus` — phosphorus ≥ 300 mg/serving (CKD caution).
- plus `category` and `cuisine` tags.

### Provenance and verification — IMPORTANT

> **All dish values are currently approximate, manually-curated estimates
> (`provenance: "manual_curation"`, `verified: false`).** They are plausible
> figures assembled from publicly-known Singapore hawker/kopitiam nutrition
> ranges and are **not yet clinically validated**. Do not present them as
> authoritative.

Provenance values:

- `manual_curation` — hand-entered estimate (all current records).
- `hpb_import` — parsed from an official HPB SG FoodID download.
- `usda_estimate` — K/P filled by `usda_fill_gaps.py`.

`verified` flips to `true` only after a human checks the record against an
authoritative source (HPB SG FoodID preferred).

### HPB SG FoodID download plan (Week 1 follow-up)

HPB's SG FoodID (formerly FOCOS/ENCF) has >3,000 items and a web **download**
button but **no public API**. Plan:

1. Manually download the curated subset (~150–300 hawker/local dishes) as CSV/XLSX.
2. Map HPB columns onto this schema; set `hpb_id` and `provenance: "hpb_import"`.
3. Where HPB lacks K/P (common), run `usda_fill_gaps.py` and mark those fields
   `usda_estimate`.
4. A human spot-checks and sets `verified: true`.

Community fallbacks if the official download is delayed: Kaggle "Singapore Hawker
Food Nutritional Information", NutriKaki (468 HPB-sourced dishes).

### How to extend

Add a row to the table in the (temporary) builder or edit `dishes.json` directly.
Keep `dish_id` unique, keep the schema keys exactly as above, and only set
`verified: true` with a cited source. Re-derive tags with the rules above.

## Synthetic patients (`patients.json`, `patients_generator.py`)

```bash
python -m data.patients_generator --n 20 --seed 0 --out data/patients.json
```

### Clinical archetypes (9)

| Archetype | Diagnoses | eGFR (mean) | K+ (mean) | Meds |
|---|---|---|---|---|
| `T2D` | T2D | 85 | 4.0 | metformin |
| `HTN` | HTN | 85 | 4.2 | ACEi |
| `T2D_HTN` | T2D, HTN | 82 | 4.1 | metformin, ACEi |
| `CKD3_T2D_HTN` | T2D, HTN, CKD stage 3 | 45 | 4.5 | metformin, ACEi, statin |
| `CKD4_T2D_HTN` | T2D, HTN, CKD stage 4 | 28 | 4.8–5.4 | insulin, ACEi, statin, phosphate binder |
| `CKD4_hyperK` | T2D, CKD stage 4, hyperkalemia | 26 | 5.5+ (rising) | + potassium binder |
| `CKD5_pre_dialysis_hyperPO4` | CKD stage 5 pre-dialysis | 18 | 5.0, PO4 6.5 | phosphate binder, EPO, statin |
| `pregnancy_T2D` | pregnancy, T2D | 90 | 4.0 | insulin (**excluded**) |
| `healthy_control` | — | 95 | 4.0 | — |

Patients are assigned archetypes round-robin, so `--n 20` covers every archetype
at least twice.

### Longitudinal labs

Each patient carries the 6 most-recent monthly values:

- `labs_K_monthly`: `[v0..v5]`, index 0 = most recent.
- `labs_PO4_monthly`: `[v0..v5]`.
- `months_offset_ago`: `[0, 1, 2, 3, 4, 5]`.

CKD patients trend upward (positive `k_trend`/`po4_trend`); healthy controls are
flat. `serum_K_meq_L` / `serum_PO4_mg_dL` always equal `labs_*_monthly[0]`.

### Reproducibility

A single integer `--seed` drives every draw. When NumPy is present the generator
uses `numpy.random.default_rng(seed)` exactly as specified. **The repo venv ships
only pydantic**, so when NumPy is absent the generator transparently falls back to
a deterministic `random.Random(seed)` shim that mirrors the subset of the
`Generator` API used (`normal`/`uniform`/`integers`/`choice`/`random`). Output is
reproducible for a given seed and RNG backend. Install NumPy later and re-run with
the same seed to regenerate; values will differ only because the RNG backend
changed (a note is printed to stderr).

`pregnancy_T2D` records set `exclude_from_careloop: true` and must never reach the
optimiser (out of CareLoop scope).

## USDA gap filler (`usda_fill_gaps.py`)

Skeleton that estimates per-serving K/P for dishes missing them, by querying
USDA FoodData Central:

```bash
# single ingredient probe
python -m data.usda_fill_gaps --ingredient "white rice" --portion-g 200

# fill gaps (cap requests!)
python -m data.usda_fill_gaps --dishes data/dishes.json --out data/dishes_filled.json --limit 10
```

- Endpoint: `https://api.nal.usda.gov/fdc/v1/foods/search`.
- Uses stdlib `urllib` only (no `requests` dependency).
- **Rate limit:** `DEMO_KEY` is shared and limited to ~30 req/hour (and ~50/day).
  Set `USDA_API_KEY` (free data.gov key) for 1,000 req/hour. A local
  `RequestBudget` caps each process at 30 requests and HTTP 429 is handled
  gracefully.
- **Never crashes:** every network/HTTP/JSON error is caught; missing values stay
  `None`. Ingredients are queried individually and summed using an equal-weight
  portion split — a deliberately crude first pass. Real precision needs recipe
  decomposition + ingredient weights (future work).
