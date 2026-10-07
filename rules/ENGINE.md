# CareLoop Rule Engine — design & usage

`rules/engine.py` turns a patient dict into a **proposed nutrient envelope** (the frozen
`shared/envelope_schema.NutrientEnvelope` contract) plus a **full rule-firing trace**
(`shared/envelope_schema.RuleFire` rows). It is a hybrid: **CLIPS forward-chaining** decides
*which* rules fire; **Python assembly** decides *what the envelope looks like*.

## Usage

```python
from rules.engine import run_rules

result = run_rules(patient_dict)     # data/patients.json shape (extra fields ignored)
envelope = result["envelope"]        # validates against shared.envelope_schema.NutrientEnvelope
trace = result["trace"]              # each row validates against shared.envelope_schema.RuleFire
```

From the repo root:

```bash
.venv/bin/python -m pytest rules/ -q     # full test suite
.venv/bin/python rules/engine.py         # smoke run on the example_trace.json patient
```

## Pipeline

1. **Compile once** (module-level, cached). Every rule in `rules/rules.json` becomes a CLIPS
   defrule with `(declare (salience <priority>))` — salience *is* the documented priority
   scale (CKD 90 > internal safety 88 > hyperkalaemia/hyperphosphataemia/med-K 85 > CKD
   general 80 > DASH 70 > ADA 60 > generic 50).
   - `diagnoses`/`meds` (`in`/`not_in`) compile to `member$` tests over multislots.
   - Numeric comparisons (`ge/lt/gt/le/eq/between`) compile to guarded tests: labs use a
     `-1.0` "unknown" sentinel, so e.g. `serum_K_meq_L < 5.0` **fails** when K is unknown
     rather than trivially passing.
   - Actions assert typed facts: `constraint(nutrient, kind, value, rule_id, priority)`,
     `exclusion(kind, value, reason, rule_id, priority)`, `clinical-flag(key, value, ...)`,
     plus a `fired(rule_id)` marker per defrule.
2. **Per patient**: `env.reset()`, assert one `(patient ...)` fact, `env.run()` to fixpoint.
   The rulebook is acyclic (rules only match the `patient` fact), so the run terminates.
3. **Python assembly** from harvested facts:
   - **Per-kg scaling**: all `energy_kcal` and `protein_g` constraint values in the rulebook
     are per-kg coefficients (kcal/kg/d, g/kg/d — including GEN-ENERGY-2535's 25–35 and
     CKD-2024-PROTEIN-055-08's 0.55–0.8). The engine multiplies by `weight_kg` (e.g. 70 kg →
     energy 1750–2450 kcal/d, protein 38.5–56 g/d), matching `example_trace.json`. The
     absolute `g` reference values for sat-fat (22 g / 13 g at a 2000 kcal reference) are
     kept as-is, matching the hand-worked example; the `%kcal` figures stay available as
     asserted flags (`sat_fat_pct_kcal_max`, `fat_pct_kcal_range`, …) for the optimiser.
   - **Conflict resolution** per `(nutrient, kind)`: higher priority wins; ties broken by
     the stricter value (max → lower, min/target → lower), then lowest `rule_id`.
     Candidates with the *same value* as the winner are merges, not conflicts. Every loser
     gets an explicit marker woven into its own trace row:
     `... | SUPERSEDED: superseded by CKD-2024-SODIUM-2000 on sodium_mg max (final value 2000 mg)`
     so the override is visible in the trace (e.g. `DASH-2025-SODIUM-2300` losing to the
     KDIGO 2000 mg ceiling).
   - **Exclusions** are deduped by `(kind, value)`, keeping the highest-priority source;
     each carries a full `CitationSource`.
   - **Scope gates**: if any rule asserts `careloop_eligible=false` (pregnancy / paediatric /
     dialysis) or `auto_envelope_suppressed` (ketoacid-risk presentation), the envelope is
     `REJECTED` with **no nutrient targets** — exclusions and the full trace are kept, and
     `notes` names the responsible rules.
4. **Trace**: one `RuleFire` row per fired rule, sorted by `(-priority, rule_id)`, with a
   condition summary (`patient_summary`), the actions applied (`action_summary`, including
   the per-kg → absolute expansion, any `SUPERSEDED` markers, and
   `[guideline / section]` attribution for set constraints), and the full citation.

## Determinism

`run_rules` is a pure function of `(patient, rules.json)`: a fixed engine clock
(`2026-01-01T00:00:00+00:00`) feeds `fired_at`/`proposed_at`, every collection is sorted,
and tie-breaks are total. The same patient always yields byte-identical output.

## Edge-case safety rules

Two internal safety rules were added to `rules.json` (guideline
`CareLoop internal safety rules`, `url`/`verbatim_quote` = null, i.e. explicitly *not*
externally sourced):

| Rule | Trigger | Effect |
|---|---|---|
| `SAFETY-HYPERK-SEVERE` (p88) | serum K ≥ 5.5 mEq/L | potassium max tightened 2400 → 2000 mg/d + urgent clinician review |
| `SAFETY-DKA-CLINICIAN-REVIEW` (p88) | T2D + HbA1c ≥ 10% | `auto_envelope_suppressed=true`, `clinician_review_required=true` → no auto envelope |

Pregnancy out-of-scope handling already existed (`SCOPE-PREGNANCY-EXCLUDE`, p95); the
engine accepts pregnancy encoded either as `pregnant: true` or as a `pregnancy` diagnosis
(the shape used in `data/patients.json`). Hyperkalaemia restriction existed at
`HYPERK-2024-POTASSIUM-2400` (K ≥ 5.0, p85) — the severe tier above layers on top of it.

## Constraint ↔ citation linkage

`NutrientConstraint` in the frozen schema carries no citation fields (`extra="forbid"`), so
per-constraint provenance is carried by (a) the constraint-producing rule's
`CitationSource` in `envelope.citations` (all fired rules are cited), and (b) the trace row
whose `action_summary` names the constraint with `[guideline / section]`. This is a
deliberate consequence of the frozen contract, not an omission.

## Fallback

No pure-Python interpreter is shipped: clipspy 1.0.6 is a hard runtime dependency of
`rules.engine` (`import clips`). `rules.clipspy_facts` remains import-safe without it, and
its `patient_fact` / template layer documents the fact-shape contract the engine mirrors
(its patient template plus an `hba1c_pct` slot).

## Known deviations from the hand-worked example

- The engine emits the sodium **target 1500** from `DASH-2025-SODIUM-1500` (that rule is in
  the example's own `all_fired_rule_ids`, but its constraint was omitted from the
  hand-worked `expected_envelope.targets`). All other targets match exactly.
- `fired_at` uses the fixed engine clock, not a wall-clock timestamp (determinism).
