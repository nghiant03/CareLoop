# CareLoop — Rules Knowledge Base (Lane A)

Structured, citable clinical rules that turn a patient profile into a proposed
**nutrient envelope** (`shared/envelope_schema.py`). This folder is the contract between
the rule engine and every downstream module (clinician gate → optimiser → RAG → UI).

## Contents

| File | Purpose |
|---|---|
| `rules.json` | The rule spec: **61 rules** — guideline-sourced rules from ADA 2026 / AHA-ACC 2025 (DASH) / KDIGO 2024+2022 / KDOQI 2020 / UK MHRA 2020 / RACGP AJGP 2023 / FDA labels, plus medication/scope/conflict extensions, and 2 internal safety rules. |
| `engine.py` | The rule engine: compiles the rulebook into CLIPS defrules, forward-chains a patient fact, assembles the envelope + `RuleFire` trace. See [`ENGINE.md`](ENGINE.md). |
| `example_trace.json` | Hand-worked trace for a CKD stage 4 + HTN + K⁺ 5.4 patient → expected envelope, 32 fired rules. |
| `clipspy_facts.py` | CLIPS `deftemplate` layer + mapping helpers mirroring the pydantic contracts. Import-safe without clipspy. |
| `neo4j_schema_design.md` | Graph schema + versioning model, with SQLite + NetworkX fallback mapping. |
| `SCHEMA_DECISION.md` | Recorded gate decision: **SQLite + NetworkX** for the prototype. |

> **Tooling note.** `clipspy` (and, for the optimiser, `pymoo` + `numpy`) are
> installed in the repo `.venv`; `rules.engine` imports `clips` directly and is
> a hard runtime dependency. `rules.json` itself is pure data and needs no
> engine. Neo4j is not used — the prototype uses SQLite + NetworkX per the
> recorded decision.

---

## 1. Rule schema

Each entry in `rules.json["rules"]`:

```jsonc
{
  "rule_id": "CKD-2024-SODIUM-2000",   // stable id, used in every citation/trace
  "guideline": "KDIGO 2024 CKD Guideline",
  "section": "Sec. 3.4 / Dietary Sodium",
  "priority": 90,                       // higher wins on conflict (salience)
  "conditions": [ { "field": "...", "op": "...", "value": ... } ],
  "actions":    [ { "type": "set_constraint", ... } ],
  "notes": "human-readable rationale",
  "url": "https://...",                 // optional
  "verbatim_quote": "..."               // optional short quote
}
```

### Priority scale (from the sprint spec)

| Tier | Value |
|---|---|
| CKD stage 3–4 | **90** |
| Hyperkalaemia / hyperphosphataemia | **85** |
| CKD (general) | **80** |
| DASH / HTN | **70** |
| ADA / T2D | **60** |
| Generic / informational | **50** |
| Scope gates (pregnancy, paediatric) | **95** |

Conflict policy: **CKD > hyperkalaemia > HTN/DASH > T2D > generic** on shared nutrients.
`CONFLICT-*` rules (priority 90) re-assert the winner and record an `assert` describing the
resolution, so the trace explains *why* a value was chosen.

---

## 2. The JSON DSL

### Conditions

```jsonc
{ "field": "<patient field>", "op": "<operator>", "value": <any> }
```

* **Operators:** `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`, `not_in`, `between`.
* **Fields:** patient-summary fields — `age`, `sex`, `weight_kg`, `diagnoses`, `egfr`,
  `serum_K_meq_L`, `serum_PO4_mg_dL`, `meds` — plus derived fields `bmi` and `pregnant`.
* **List fields (`diagnoses`, `meds`):** `in` = *intersection non-empty* ("has any of");
  `not_in` = *intersection empty* ("has none of"). For scalar fields `in` is set membership.
* **`between`** is inclusive `[low, high]`.
* **Empty `conditions: []`** = applies to every patient (universal default rule).
* All conditions are ANDed.

### Actions

```jsonc
{ "type": "set_constraint", "nutrient": "<NutrientKind>", "kind": "<ConstraintKind>", "value": 2000 }
{ "type": "exclude",        "kind": "<ExclusionKind>", "value": "potassium_chloride", "reason": "..." }
{ "type": "assert",         "key": "<string>", "value": <any> }
```

* `NutrientKind` and `ConstraintKind` are exactly the enums in `shared/envelope_schema.py`.
* `unit` is **not** carried in the action — the engine fills the canonical unit from the
  `NutrientKind` (schema validator enforces the match).
* **Weight-scaled nutrients:** for `protein_g` and `energy_kcal`, a `set_constraint` value is
  expressed **per kg of body weight** (`g/kg/d`, `kcal/kg/d`). The engine multiplies by
  `patient.weight_kg` and emits absolute values in the `NutrientEnvelope`. All other
  nutrients are absolute daily totals. Example: CKD protein `min 0.55` × 70 kg = **38.5 g/d**.
* `exclude` produces an `ExclusionFlag` (hard exclusion). `assert` records a non-nutrient
  fact (flags, cautions, resolution notes) consumed by later rules or the explanation views.

---

## 3. How to load

```python
import json

spec = json.load(open("rules/rules.json"))
rules = spec["rules"]                          # 61 dicts
by_id = {r["rule_id"]: r for r in rules}
```

The production engine is `rules/engine.py` — the rulebook is compiled into
CLIPS defrules (salience = priority), a patient fact is asserted and
forward-chained to fixpoint, and Python assembles the envelope. Usage,
pipeline, determinism guarantees and known deviations: **see
[`rules/ENGINE.md`](ENGINE.md)**. Quick start:

```python
from rules.engine import run_rules

result = run_rules(patient_dict)   # data/patients.json shape
envelope, trace = result["envelope"], result["trace"]
```

Reference evaluator (used to verify this spec; no clipspy needed):

```python
OPS = {"eq","ne","lt","le","gt","ge","in","not_in","between"}

def matches(rule, p):
    def ev(c):
        f, op, v, pv = c["field"], c["op"], c["value"], p.get(c["field"])
        return {
            "eq": lambda: pv == v,
            "ne": lambda: pv != v,
            "lt": lambda: pv is not None and pv < v,
            "le": lambda: pv is not None and pv <= v,
            "gt": lambda: pv is not None and pv > v,
            "ge": lambda: pv is not None and pv >= v,
            "between": lambda: pv is not None and v[0] <= pv <= v[1],
            "in": lambda: bool(set(pv or []) & set(v)),
            "not_in": lambda: not (set(pv or []) & set(v)),
        }[op]()
    return all(ev(c) for c in rule["conditions"])
```

Resolve conflicts by taking, per `(nutrient, kind)`, the action from the **highest-priority**
fired rule; for `max` prefer the *lowest* value and for `min` the *highest* value (stricter
wins) at equal priority.

---

## 4. Worked example trace

`example_trace.json` walks a single patient end-to-end.

**Input** — `SYN-0007`: 62 M, 70 kg, `CKD_stage_4` (eGFR 22), `HTN`, serum K⁺ 5.4 mEq/L,
serum PO₄ 4.0 mg/dL, meds `ACEi` + `loop_diuretic`.

**Expected envelope (PROPOSED):**

| Nutrient | Constraint | Source rule(s) |
|---|---|---|
| sodium | max **2000 mg/d** | `CKD-2024-SODIUM-2000` (p90) over `DASH-2025-SODIUM-2300` (p70) → `CONFLICT-SODIUM-CKD-WINS` |
| protein | **38.5–56 g/d** (0.55–0.8 g/kg × 70) | `CKD-2024-PROTEIN-055-08`, reinforced by `KDOQI-2020-PROTEIN` |
| energy | **1750–2450 kcal/d** (25–35 kcal/kg × 70) | `CKD-2024-ENERGY-2535` |
| potassium | max **2400 mg/d** | `HYPERK-2024-POTASSIUM-2400` (p85) over DASH 4700 target → `CONFLICT-K-DASH-VS-CKD` |
| fiber | min **30 g/d** | `DASH-2025-FIBER-30` (stricter than ADA/generic 25) |
| sat fat | max **13 g/d** | `DASH-2025-SATFAT-6PCT` |
| phosphorus | *(no ceiling)* | `CKD-2024-PHOSPHORUS-INDIV` — PO₄ 4.0 < 4.5, individualised |

**Exclusions:** `ingredient:potassium_chloride`, `dish_category:high_potassium_foods`,
`dish_category:phosphate_additive_processed`.

**Why this is the answer**

1. CKD stage 4 fires the p90 sodium rule → 2000 mg; DASH also fires at p70 (2300) but loses.
2. Serum K⁺ 5.4 ≥ 5.0 fires the p85 hyperkalaemia ceiling → 2400 mg. The DASH 4700 mg
   *target* never fires (its `not_in CKD` guard fails), and `CONFLICT-K-DASH-VS-CKD` records
   the override. `CKD-2024-POTASSIUM-INDIV` does **not** fire (it needs K⁺ < 5.0), correctly
   avoiding a "no restriction" assertion.
3. Protein/energy are per-kg rules scaled to the 70 kg patient.
4. PO₄ is normal, so no phosphorus ceiling — only the additive exclusion applies.
5. ACEi adds a potassium caution flag (`MED-ACEI-ARB-K-CAUTION`), now backed by the cited
   `MED-RASI-K-CAUTION` (KDIGO 2024 Practice Point 3.6.3); the `loop_diuretic` med adds the
   cited K⁺/Mg monitoring flag `MED-LOOP-K-MG` (AHA/ACC 2025 §5.2.8).

**Fired-rule count:** 32 (full list in `example_trace.json["all_fired_rule_ids"]`), well above
the ≥5 requirement. `example_trace.json` carries a representative `fired_rules` array of
14 `RuleFire` rows plus the full id list.

---

## 5. Rule coverage map

| Guideline | Rules | Examples |
|---|---|---|
| ADA 2026 (T2D) | 8 | sodium 2300, fiber 25–30, sat fat <10% kcal, carb 26–45% kcal, SSB exclusion |
| AHA/ACC 2025 + DASH (HTN) | 8 | sodium 2300/ideal 1500, K ~4700, fiber 30, sat fat 6% kcal, alcohol |
| KDIGO 2024 (CKD) | 10 | sodium 2000, protein 0.55–0.8 g/kg, protein ceiling 1.3, energy 25–35 kcal/kg, K/P individualised, phosphate additives, eGFR staging |
| KDOQI 2020 | 1 | protein basis reinforcement |
| Hyperkalaemia | 4 | K ceiling 2400, high-K food + KCl exclusions, monitoring |
| Hyperphosphataemia | 3 | P ceiling 800, additive exclusion, monitoring |
| Medication interactions | 13 | ACEi/ARB K caution (KDIGO 2024), RASi+spironolactone alert (UK MHRA 2020), SGLT2i volume (KDIGO 2022), thiazide/loop electrolytes (AHA/ACC 2025), phosphate-binder timing (RACGP 2023), warfarin vitamin-K consistency (FDA label), metformin B12 (ADA 2026) |
| Generic defaults | 6 | energy, protein RDA, fiber, sodium, fat %, sugar % |
| Scope gates | 3 | pregnancy, paediatric, dialysis exclusions |
| Conflict resolution | 3 | sodium CKD-wins, K DASH-vs-CKD (elevated / normal) |

### Citation caveat
`url` and `verbatim_quote` values are **illustrative references** intended to point at the
correct guideline document/section. They must be re-verified against the primary sources
before any publication or clinical use; several quotes are paraphrases of standard guideline
language, not certified verbatim extracts.

---

## 6. Verification

```bash
python -c "import json; print(len(json.load(open('rules/rules.json'))['rules']))"   # 61 (59 + 2 internal safety rules)
python -c "from shared.envelope_schema import NutrientEnvelope; print('ok')"
python rules/clipspy_facts.py                                                        # prints availability
```

---

## 7. Rule engine

`rules/engine.py` implements `run_rules(patient: dict) -> {"envelope", "trace"}`: the
rulebook is compiled into CLIPS defrules (salience = priority), a patient fact is asserted
and forward-chained, and Python assembles the `NutrientEnvelope` (per-kg scaling,
priority-based conflict resolution with visible `SUPERSEDED` markers, scope gates) plus a
full `RuleFire` trace. Usage, design, determinism and deviations: **see
[`rules/ENGINE.md`](ENGINE.md)**. Tests: `.venv/bin/python -m pytest rules/ -q`.
