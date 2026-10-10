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
   The engine owns a lock around lazy environment initialization and the complete
   reset/assert/run/harvest/cleanup sequence. All callers share this protection.
   Weight must be finite and positive before execution. Both lab spellings are
   accepted; explicit wire aliases take precedence, including null values.
   New snapshots use `snapshot_version=2` and retain BMI, pregnancy and HbA1c.
   Version 1 remains readable; absent inputs are unknown, not reconstructed.
3. **Python assembly** from harvested facts:
   - **Per-kg scaling**: all `energy_kcal` and `protein_g` constraint values in the rulebook
     are per-kg coefficients (kcal/kg/d, g/kg/d — including GEN-ENERGY-2535's 25–35 and
     CKD-2024-PROTEIN-055-08's 0.55–0.8). The engine multiplies by `weight_kg` (e.g. 70 kg →
     energy 1750–2450 kcal/d, protein 38.5–56 g/d), matching `example_trace.json`. The
     absolute `g` reference values for sat-fat (22 g / 13 g at a 2000 kcal reference) are
     kept as-is, matching the hand-worked example; the `%kcal` figures stay available as
     asserted flags (`sat_fat_pct_kcal_max`, `fat_pct_kcal_range`, …) for the optimiser.
   - **Conflict resolution** per `(nutrient, kind)`: higher priority wins. Equal
     priority chooses the lower MAX ceiling, higher MIN soft floor, or lower TARGET
     soft aim, then lowest `rule_id`. TARGET ordering is deterministic, not a
     stricter hard bound. MIN and TARGET remain soft objectives.
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

`NutrientConstraint.provenance` can record the exact kind, value, unit, envelope
identity/version, author, and citation. `shared/provenance.py` fills missing
provenance from matching trace actions; clinician target replacements receive
clinician-authored provenance. All fired rules retain their trace and citations,
but firing does not establish authorship of the final constraint. Legacy matching
depends on the engine's `action_summary` format; arbitrary prose is not equivalent.

## Medication–nutrient interaction rules (stretch feature #1)

Eight medication–nutrient rules in `rules/rules.json` carry guideline/section/URL
references and quote text. Primary-source verification is not established by this
repository; the [citation caveat](README.md#citation-caveat) applies to these rows
as well. Re-verify quotations before publication or clinical use. They use only the existing
action kinds (`assert` clinical flags — no new constraint kinds) and are ANDed like every
other condition set, including a two-`meds`-condition conjunction for the combination alert.

| Rule | Priority | Fires on | Flag keys |
|---|---|---|---|
| `MED-RASI-K-CAUTION` | 85 | ACEi/ARB (class token `ACEi` in the dataset; `ARB` + generic spellings accepted) | `rasi_k_monitoring`, `assess_dietary_potassium` — KDIGO 2024 CKD, Practice Point 3.6.3 |
| `MED-RASI-KSPARING-ALERT` | 88 | **ACEi/ARB AND spironolactone** (two `meds in` conditions ANDed) | `rasi_k_sparing_interaction`, `med_interaction_high_risk` — UK MHRA Drug Safety Update 2020 |
| `MED-SGLT2I-VOLUME` | 65 | SGLT2i (`SGLT2i` token + generic spellings) | `sglt2i_volume_caution` — KDIGO 2022 Diabetes in CKD, Practice Point 1.3.4 |
| `MED-THIAZIDE-ELECTROLYTES` | 70 | thiazide (`thiazide` token + generic spellings) | `thiazide_electrolyte_monitoring` — 2025 AHA/ACC Hypertension §5.2.8 |
| `MED-LOOP-K-MG` | 70 | loop diuretic (`loop_diuretic` token + generic spellings) | `loop_diuretic_k_mg_monitoring` — FDA Lasix label / AHA/ACC §5.2.8 (quote from the AHA/ACC guideline; noted in the rule) |
| `MED-PHOSPHATE-BINDER-TIMING` | 65 | phosphate binder (dataset token `phosphate_binder` + `sevelamer`/`calcium_acetate`) | `phosphate_binder_timing` — RACGP AJGP 2023 CKD-MBD |
| `MED-WARFARIN-VITK` | 75 | warfarin | `warfarin_vitamin_k_consistency` — FDA Coumadin label, Instructions for Patients |
| `MED-METFORMIN-B12` | 60 | metformin (dataset token) | `metformin_b12_assessment` — ADA Standards of Care 2026, Rec. 3.10 |

Notes:

* **Vocabulary.** The live dataset (`data/patients.json`) encodes meds as class tokens
  (`ACEi`, `metformin`, `phosphate_binder`, `statin`, `insulin`, `potassium_binder`,
  `erythropoietin`). Each rule's `in`-list therefore contains the dataset token **plus**
  common generic spellings (e.g. `lisinopril`, `furosemide`, `sevelamer`) so future profiles
  using drug names still match; unmatched rules are inert for today's cohort.
* **Conjunction.** Rule 2 expresses "ACEi/ARB present AND spironolactone present" as two
  separate `meds` conditions — the compiler emits one `member$` test per condition and CLIPS
  ANDs them, so no engine change was needed.
* **Surface.** The flags land in the envelope `notes` "Cautions/asserts" line and, because
  every fired rule contributes its `CitationSource`, chat citations and the clinician
  explanation pick up `guideline`/`section`/`url`/`verbatim_quote` automatically.
* **No nutrient constraints.** These rules deliberately set no nutrient ceiling/target —
  potassium/phosphorus/sodium levels remain governed by the lab- and diagnosis-driven rules;
  the med flags only add monitoring/diet-counselling instructions.
* **Determinism** is untouched: the flags are harvested and sorted by
  `(key, value, rule_id)` like all other clinical flags.
* `rules/example_trace.json` pins the SYN-0007 fired-rule IDs, including
  `MED-RASI-K-CAUTION` and `MED-LOOP-K-MG`. Tests check this fixture's coverage.

## Fallback

No pure-Python interpreter is shipped: running `rules.engine` requires clipspy.
Its guarded import allows the module to load without CLIPS, but a rule run then
raises `RuntimeError`. `rules.clipspy_facts` supplies import-safe reference helpers;
the active engine uses separate templates, including an `hba1c_pct` patient slot.

## Known deviations from the hand-worked example

- The engine emits the sodium **target 1500** from `DASH-2025-SODIUM-1500` (that rule is in
  the example's own `all_fired_rule_ids`, but its constraint was omitted from the
  hand-worked `expected_envelope.targets`). All other targets match exactly.
- `fired_at` uses the fixed engine clock, not a wall-clock timestamp (determinism).
