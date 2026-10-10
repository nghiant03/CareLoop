# CareLoop — Data Layer (Lane C: Data & Mining)

The data & mining workstream deliverables: a curated Singapore dish
nutrient table, a deterministic synthetic patient generator, and a USDA
FoodData Central gap-filler for potassium/phosphorus. The knowledge-discovery
modules built on top of this data (trends, clustering, substitutions) live in
[`backend/mining/`](../backend/mining/README.md).

## Contents

| File | Purpose |
|---|---|
| `dishes.json` | 214 curated Singapore dish records (energy, protein, Na, K, P, carbs, fat, sat fat, fibre, sugar): 190 `manual_curation` + 24 `curated_renal_replenishment`. |
| `patient.py` | Pydantic `Patient` model — extends the canonical `shared.envelope_schema.PatientSummary` with archetype, vitals, and longitudinal labs. |
| `patients_generator.py` | Deterministic generator for N synthetic patients from 9 clinical archetypes. |
| `patients.json` | Generated output (default 20 patients, seed 0). |
| `usda_fill_gaps.py` | Skeleton: estimate missing K/P from USDA FDC by ingredient. |

## Dish data (`dishes.json`)

214 records across 8 categories: `hawker` (62), `zi_char` (32), `kopitiam` (28),
`cai_png` (28), `drink` (20), `soup` (19), `healthy` (18), `dessert` (7).

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

Nutrient tags encode per-serving thresholds from the approximate catalogue values:

- `high_sodium` — sodium > 1000 mg/serving.
- `high_potassium` — potassium ≥ 700 mg/serving (CKD caution).
- `high_phosphorus` — phosphorus ≥ 300 mg/serving (CKD caution).
- plus `category` and `cuisine` tags.

Cooking/protein-role tags are curated from dish preparation and ingredients,
not derived from fat or saturated-fat values:

- `deep_fried` — a deep-fried dish or a dish containing a recorded deep-fried
  component, such as fried fish, tofu puffs or you tiao. Stir-fried noodles/rice,
  grilled satay, braised pork and baked fish do not qualify merely for high fat.
- `lean_protein` — a non-deep-fried dish with fish/seafood, lean meat/poultry or
  tofu as a substantive protein component. Plain rice, vegetable sides, drinks
  and sweet desserts do not qualify merely for low saturated fat.

These roles describe the curated recipe, not a clinically verified nutrition
claim or a guarantee about every vendor's preparation. Review recipe variants
before reusing the tags. Optimizer preferences and literal exclusions consume
these stable tag names; numeric nutrient limits remain separate.

### Provenance and verification — IMPORTANT

> **All dish values are currently approximate curated estimates
> (`provenance: "manual_curation"` or `"curated_renal_replenishment"`,
> `verified: false`).** They are plausible
> figures assembled from publicly-known Singapore hawker/kopitiam nutrition
> ranges and are **not yet clinically validated**. Do not present them as
> authoritative.

Provenance values:

- `manual_curation` — hand-entered estimate (the 190 original records).
- `curated_renal_replenishment` — 24 dishes (SG0191–SG0214) added so the renal /
  diabetes envelopes are reachable: low-sodium / low-phosphorus mains with
  enough energy, high-potassium low-phosphorus fruit and vegetable sides, and
  higher-fibre staples. Values are curated estimates, not clinically validated
  (see the warning above). Their potassium-rich items sit below the
  `high_potassium` tag threshold (700 mg/serving) but above the rulebook
  exclusion threshold — `backend/optim/exclusion_mapping.py` excludes dishes
  over 500 mg potassium/serving for hyperkalaemia envelopes.
- `hpb_import` — parsed from an official HPB SG FoodID download.
- `usda_estimate` — K/P filled by `usda_fill_gaps.py`.

`verified` flips to `true` only after a human checks the record against an
authoritative source (HPB SG FoodID preferred).

### HPB SG FoodID download plan (pending follow-up)

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
`verified: true` with a cited source. Re-derive nutrient tags from the thresholds
above and review cooking/protein roles from the recipe, not numeric proxies.

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

A single integer `--seed` drives every draw. NumPy is installed in the repo
`.venv`, so the generator uses `numpy.random.default_rng(seed)` exactly as
specified. When NumPy is absent it transparently falls back to a deterministic
`random.Random(seed)` shim that mirrors the subset of the `Generator` API used
(`normal`/`uniform`/`integers`/`choice`/`random`). Output is reproducible for a
given seed and RNG backend; values differ between backends (a note is printed
to stderr).

`pregnancy_T2D` and `CKD5_pre_dialysis_hyperPO4` records set
`exclude_from_careloop: true` and must never reach the
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
  `RequestBudget` caps a file import at 30 attempted requests. Standalone callers
  must share a budget to bound a whole run. HTTP 429 or local exhaustion stops
  file imports, preserving completed dishes and leaving the interrupted dish
  unchanged. CLI diagnostics report the actual shared budget. Resume with a new
  explicitly budgeted run; waiting or changing keys does not reset a local counter.
- Network/HTTP/JSON search failures other than rate limits return unknown values.
  Invalid inputs or malformed response shapes may raise. Changed estimates clear
  verification and refresh K/P threshold tags; cooking/protein roles are preserved.
  Ingredients are queried individually and summed using an equal-weight
  portion split — a deliberately crude first pass. Real precision needs recipe
  decomposition + ingredient weights (future work).
