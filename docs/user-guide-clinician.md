# Clinician guide

How to review a proposed nutrient envelope, approve it, and interpret the
generated meal plan, trend flags and knowledge-base stats. Command examples use
`curl` against `http://127.0.0.1:8000`; the same flows are available in the
web UI (Clinician review screen). Note: envelopes, traces and created patients
are held in process-local stores — restarting the backend clears them.

## 1. Pick a patient and generate the proposed envelope

```bash
curl -sS http://127.0.0.1:8000/patients | jq '.patients[] | {patient_id, diagnoses, serum_K_meq_L, egfr}'

curl -sS -X POST http://127.0.0.1:8000/rules/run \
  -H 'content-type: application/json' -d '{"patient_id":"P0005"}' > run.json
jq '.envelope.status, [.envelope.targets[] | {nutrient:.nutrient, kind:.kind, value:.value, unit:.unit}]' run.json
```

The response contains two things:

- **`envelope`** — the proposed nutrient constraints, exclusions, citations and
  status `PROPOSED`.
- **`trace`** — one `RuleFire` row per fired rule, sorted by descending
  priority: `rule_id`, `priority`, `patient_summary` (which conditions matched),
  `action_summary` (what the rule set, including per-kg → absolute expansion),
  and the full citation (guideline, section, quote, URL).

Out-of-scope patients (pregnancy, paediatric, dialysis, ketoacid-risk) get
`status: "REJECTED"` with **no nutrient targets** — the trace names the
responsible scope rules. Such patients never proceed to planning.

## 2. Read the constraint table and the fired-rule trace

The constraint table lists every target the engine produced. When several
guidelines disagree, the conflict is resolved by priority — the losing rule
stays visible in the trace:

```
DASH-2025-SODIUM-2300   p70   set sodium_mg max = 2300 mg/d
      | SUPERSEDED: superseded by CKD-2024-SODIUM-2000 on sodium_mg max
      |             (final value 2000 mg)
```

Reading order: highest priority first (CKD 90 > internal safety 88 >
hyperkalaemia/hyperphosphataemia/medication-K 85 > CKD general 80 > DASH 70 >
ADA 60 > generic 50). Per-kg rules show the expansion explicitly, e.g.
`set protein_g max = 0.8 g/kg/d -> 43.44 g/d (weight 54.3 kg)`.

For a structured clinician view of one envelope:

```bash
curl -sS http://127.0.0.1:8000/envelopes/ENV-P0005-001/explanation | jq
```

This returns the envelope, the priority basis, the fired rules with citations,
and the list of conflicts resolved (which rule won, on which nutrient, and why).

## 3. Approve, edit or reject

```bash
# approve (PROPOSED or EDITED -> APPROVED)
curl -sS -X POST http://127.0.0.1:8000/envelopes/ENV-P0005-001/approve \
  -H 'content-type: application/json' -d '{"approved_by":"Dr.Demo","note":""}'

# edit targets (-> EDITED; approval is cleared, re-approval required)
curl -sS -X POST http://127.0.0.1:8000/envelopes/ENV-P0005-001/edit \
  -H 'content-type: application/json' \
  -d '{"targets":[{"nutrient":"sodium_mg","kind":"max","value":1800,"unit":"mg"}],"edited_by":"Dr.Demo"}'

# reject (-> REJECTED, terminal for this envelope id)
curl -sS -X POST http://127.0.0.1:8000/envelopes/ENV-P0005-001/reject \
  -H 'content-type: application/json' -d '{"reason":"too restrictive for this patient"}'
```

Until an envelope is `APPROVED`, every downstream consumer is blocked: the plan
endpoint answers `HTTP 409 {"error": "envelope_not_approved", "status": "..."}`,
and chat answers flag the envelope as not yet approved. Editing re-opens the
gate on purpose — the edited numbers must be re-confirmed by a clinician.

## 4. Generate and interpret the 7-day plan

```bash
curl -sS -X POST http://127.0.0.1:8000/plans \
  -H 'content-type: application/json' -d '{"patient_id":"P0005"}' > plan.json
```

Key fields:

- **`feasible` / `engine` / `violation_count`** — the optimiser guarantees
  `violation_count == 0` for any plan it returns (`engine` is `pymoo`, or
  `greedy-fallback` when the GA front needed repair).
- **`days[]`** — 7 days × 3 meals; each slot carries the dish with its nutrient
  profile.
- **`totals[]`** — per nutrient per day: the achieved `value`, the `targets`
  (min/max/target with units) and a `compliant` flag. Compare totals against
  targets to sanity-check the plan.
- **`relaxed_constraints`** — disclosed MIN-floor adjustments. Guideline floors
  the dish pool provably cannot reach (today: fibre — the 190-dish pool tops
  out at 8 g/dish, so 3 meals reach at most 24 g/day against a 30 g guideline
  floor) are lowered to the achievable bound **before** solving, and every
  adjustment is reported here with `requested`, `relaxed_to` and the reason.
  This is the one place where a guideline value is knowingly not met, and it is
  always explicit.
- **`infeasibility_reason`** — when the allowed pool cannot satisfy the
  envelope at all, the response is an explicit diagnosis:
  `feasible=false`, `engine="infeasible"`, `violations[]` naming the problem
  (e.g. "no feasible plan reachable from the allowed pool"), `days: []`.
  Strict renal envelopes (narrow protein/energy windows plus sodium ceilings)
  can hit this on the current dish pool; the response is safe to show — nothing
  infeasible is silently plated.
- **`explanation`** — the patient-facing view (plain-language daily targets,
  avoid-list, "why" bullets with guideline attributions, and
  `relaxation_notes` when floors were relaxed). Review it as part of sign-off:
  this is what the patient will read.

## 5. Cohort trend flags

```bash
curl -sS http://127.0.0.1:8000/mining/trends | jq
```

Theil–Sen slopes over the 6 most-recent monthly K⁺ and PO₄ values for every
patient. Each flag: `patient_id`, `analyte`, `slope_per_month`, the
chronological `values`, `projected_3mo`, `severity` (`urgent` when the latest
value already exceeds the alert level — K⁺ ≥ 5.0, PO₄ ≥ 4.6 — or the projection
crosses the threshold; `review` otherwise) and a one-line `reason`. Sorted
urgent-first. Use these to prioritise which patients need a new envelope.

## 6. Dish substitutions

```bash
curl -sS 'http://127.0.0.1:8000/mining/substitutions?dish_id=SG0001&k=3' | jq
```

Nutrient-distance-ranked alternative dishes for a plan item, with a plain
`reason` (same category/cuisine, lower sodium/potassium/phosphorus, ...).
Useful when a patient wants to swap a dish without breaking the envelope.

## 7. Knowledge-base stats

```bash
curl -sS http://127.0.0.1:8000/kb/stats | jq
```

Node/edge counts of the versioned KB (rules, dishes, constraints, citations),
the current version tag, and the retrieval-chunk count. Quick sanity check
that the backend loaded `rules/rules.json` + `data/dishes.json`.

## 8. Grounded chat

`POST /chat` answers nutrition-guidance questions in plain language, citing the
guideline behind every answer. Out-of-scope questions (diagnoses, medication
changes, emergencies, non-nutrition topics) are escalated with a safety message
instead of answered, and low-confidence questions are refused with a
see-your-clinician pointer. The patient's latest envelope is included as
context; if it is not APPROVED, answers say so.
