# Clinician guide

How to review a proposed nutrient envelope, approve it, and interpret the
generated meal plan, adherence summaries, trend flags and knowledge-base
stats. Command examples use
`curl` against `http://127.0.0.1:8000`; the same flows are available in the
web UI (Clinician review and Adherence screens). Clinical state persists in
PostgreSQL across backend restarts.

This is an academic showcase with simulated roles, not real clinical review.
`CARELOOP_APPROVAL_MODE=auto` is the demo default: eligible new proposals pass
through the approval lifecycle with a labelled system actor, not a clinician.
Scope-rejected proposals stay excluded. Edits always require manual re-approval.
Set `CARELOOP_APPROVAL_MODE=clinician` to follow the manual workflow below.

## 1. Pick a patient and generate the proposed envelope

```bash
curl -sS http://127.0.0.1:8000/patients | jq '.patients[] | {patient_id, diagnoses, serum_K_meq_L, egfr}'

curl -sS -X POST http://127.0.0.1:8000/rules/run \
  -H 'content-type: application/json' -d '{"patient_id":"P0005"}' > run.json
jq '.envelope.status, [.envelope.targets[] | {nutrient:.nutrient, kind:.kind, value:.value, unit:.unit}]' run.json
```

The response contains two things:

- **`envelope`** — the proposed nutrient constraints, exclusions, citations and
  status `PROPOSED` in clinician mode, or `APPROVED` in auto demo mode.
- **`trace`** — one `RuleFire` row per fired rule, sorted by descending
  priority: `rule_id`, `priority`, `patient_summary` (which conditions matched),
  `action_summary` (what the rule set, including per-kg → absolute expansion),
  and the full citation (guideline, section, quote, URL).

Out-of-scope patients (pregnancy, paediatric, dialysis — by diagnosis or
CKD stage 5 / eGFR < 15 — and ketoacid-risk) get `status: "REJECTED"` with
**no nutrient targets** — the trace names the responsible scope rules. Such
patients never proceed to planning, and the approval endpoint refuses to
approve their envelopes (see section 3).

Medication–nutrient interaction rules fire alongside the nutrient rules: they
add **cautions/asserts** to the envelope notes (for example
`rasi_k_monitoring`, `medication_k_risk`, `metformin_b12_assessment`,
`phosphate_binder_timing`, `warfarin_vitamin_k_consistency`) with the
guideline citation in the trace — KDIGO 2024/2022, UK MHRA Drug Safety Update
2020, AHA/ACC 2025, FDA labels, ADA 2026, RACGP AJGP 2023. Read them as
review prompts, not automatic constraint changes.

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

Live planning requires an `APPROVED`, scope-eligible envelope with nonempty
targets; otherwise the plan endpoint answers
`HTTP 409 {"error": "envelope_not_approved", "status": "..."}`. Informational
views remain available, and chat does not present unapproved numbers as personal
guidance. Editing clears approval — the edited numbers must be re-confirmed.
See [the approval-gate contract](ARCHITECTURE.md#2-the-approval-gate-invariant).

Two more guards:

- **Scope cannot be overridden through approval.** Approving a REJECTED,
  scope-ineligible, or empty-target envelope returns
  `HTTP 422 {"error": "out_of_scope_envelope"}` instead of approving it.
- **Re-running the engine never overwrites history.** A fresh `/rules/run`
  for a patient who already has an envelope mints the next sequential id
  (`ENV-P0005-002`, ...) — prior envelopes, including APPROVED ones, and
  their traces stay intact.

Also note: clinician edits append an explicit `CLINICIAN-EDIT` trace row, so
edited numbers are never attributed to a guideline in explanations or chat.

## 4. Generate and interpret the 7-day plan

```bash
curl -sS -X POST http://127.0.0.1:8000/plans \
  -H 'content-type: application/json' -d '{"patient_id":"P0005"}' > plan.json
```

Key fields:

- **`feasible` / `engine` / `violation_count`** — the optimiser guarantees
  `violation_count == 0` for any delivered plan. `engine` identifies the search
  path, including main/side composition or a single-dish fallback; it is not
  itself a measure of nutritional adequacy.
- **`days[]`** — 7 days × 3 meals; slots can contain a main and optional side,
  with dish nutrient profiles and combined meal totals.
- **`totals[]`** — per nutrient per day: the achieved `value`, the `targets`
  (min/max/target with units) and a `compliant` flag. Compare totals against
  targets to sanity-check the plan.
- **`relaxed_constraints`** — disclosed soft MIN-floor adjustments retained
  when the single-dish fallback is used, with `requested`, `relaxed_to` and a
  reason. Its three-dish-per-day bound does not limit main/side composition,
  which scores the original aims and clears these adjustments on success.
- **`adequacy[]`** — delivery against the original approved MIN/TARGET aims,
  even when a fallback floor was relaxed. MIN shortfall and absolute TARGET
  deviation are separate from hard feasibility: a feasible plan can miss an
  aim without any retained relaxation. The compatibility fields `shortfall`
  and `shortfall_pct` cover both kinds of gap.
- **`infeasibility_reason` / `infeasibility_status`** — when no hard-feasible
  plan is found, the response is an explicit diagnosis:
  `feasible=false`, `engine="infeasible"`, `violations[]` naming the problem
  (e.g. "no feasible plan reachable from the allowed pool"), `days: []`.
  The status distinguishes a proven single-dish limit from search exhaustion;
  neither is a proof that every possible composed meal is impossible. Strict
  renal envelopes can be difficult to satisfy; nothing infeasible is plated.
- **`explanation`** — the patient-facing view (plain-language daily targets,
  avoid-list, "why" bullets with guideline attributions, and
  `relaxation_notes` when floors were relaxed). Review it as part of sign-off:
  this is what the patient will read.

## 5. Cohort trend flags

```bash
curl -sS http://127.0.0.1:8000/mining/trends | jq
```

Theil–Sen slopes over dated K⁺/PO₄ observations when present, otherwise the
fixture monthly series. Sparse dated series can still flag an urgent latest
value. Each flag: `patient_id`, `analyte`, `slope_per_month`, an
EWMA-weighted `ewma_slope_per_month` (half-life 2 months — recent months count
more), the chronological `values`, `projected_3mo`, `severity` (`urgent` when
the latest value already exceeds the alert level — K⁺ ≥ 5.0, PO₄ ≥ 4.6 — or
the projection crosses the threshold; `review` otherwise) and a one-line
`reason`. When the Theil–Sen slope trips the threshold but the EWMA slope does
not, an urgent trend can be de-escalated and the reason says so; an urgent latest
dated observation remains urgent. Sorted
urgent-first. Use these to prioritise which patients need a new envelope.

## 6. Dish substitutions

```bash
curl -sS 'http://127.0.0.1:8000/mining/substitutions?dish_id=SG0001&k=3' | jq
```

Renal-weighted nutrient-distance-ranked alternative dishes for a plan item
(sodium/potassium/phosphorus count double — the minerals CKD patients must
watch), with a plain
`reason` (same category/cuisine, lower sodium/potassium/phosphorus, ...).
These generic suggestions are not validated against a patient's plan. Supply
`patient_id` for plan-context validation and per-day deltas; unapproved
suggestions are informational. Applying a swap via `/mining/swaps/apply`
requires a ready approved envelope and saves a new derived plan.

## 7. Adherence: what the patient actually ate

Patients log their real meals in the web UI (Adherence screen) or via the API,
and each logged date is measured against its **historically effective approved**
envelope. Dates without approval coverage remain unattributed; current targets
are never applied retroactively:

```bash
# log a meal (upsert per slot — logging lunch again replaces its saved items)
curl -sS -X POST http://127.0.0.1:8000/adherence/log \
  -H 'content-type: application/json' \
  -d '{"patient_id":"P0005","date":"2026-10-08","meal":"lunch","dish_id":"SG0001"}'

# per-day summary for the last 14 days
curl -sS 'http://127.0.0.1:8000/adherence/P0005/summary?days=14' | jq

# deviation series + trend flags
curl -sS 'http://127.0.0.1:8000/adherence/P0005/deviation' | jq
```

How to read the summary:

- Each logged day totals its dishes per nutrient and classifies them against
  the envelope with the same hard/soft semantics the optimiser uses:
  exceeding a **MAX ceiling is a `hard_violation`**; falling short of a **MIN
  floor** or missing a **TARGET** is a `soft_gap` (a soft aim, not a
  violation). `aggregate` rolls this up into `hard_violation_days` and
  per-nutrient counts.
- Per-day `envelope_id`/`envelope_version` and `envelope_versions_used` identify
  the historical comparison targets. Uncovered dates appear in
  `unattributed_days`, not in target comparisons. Top-level envelope status and
  `informational_only` describe the latest envelope for compatibility; they do
  not replace historical approval coverage.
- Only complete days (breakfast, lunch and dinner logged) enter soft-gap
  aggregates and trends. Partial-day hard violations remain visible.
- The deviation endpoint returns a per-nutrient exposure series (magnitude in
  the "bad" direction per day) and Theil–Sen trend flags: `direction`
  `worsening`/`improving`, `severity` `alert` (worsening with the latest or
  3-day-projected exposure ≥ 25% of the limit) or `review`, and the slope in
  percentage-points/day. A `worsening` flag means the logged diet is drifting
  further from the envelope over time — a concrete prompt for a review
  conversation.

The dish ids in meal logs come from the dish catalogue:

```bash
curl -sS 'http://127.0.0.1:8000/dishes?category=hawker&search=chicken' | jq '.count, .dishes[0]'
curl -sS http://127.0.0.1:8000/dishes/SG0001 | jq
```

## 8. Knowledge-base stats

```bash
curl -sS http://127.0.0.1:8000/kb/stats | jq
```

Node/edge counts of the versioned KB (rules, dishes, constraints, citations),
the current version tag, and the retrieval-chunk count. Quick sanity check
that the backend loaded the external rule/dish fixtures or the selected published release.

## 9. Grounded chat

`POST /chat` answers nutrition-guidance questions in plain language, citing the
guideline behind every answer. Out-of-scope questions (diagnoses, medication
changes — including phrasings like *"should I stop taking metformin?"* —,
emergencies including metabolic emergencies, non-nutrition topics) are
escalated with a safety message instead of answered, and low-confidence
questions are refused with a see-your-clinician pointer. The patient's latest
envelope is included as context; its numbers are quoted only when the envelope
is APPROVED — a PROPOSED/EDITED envelope gets pending-review phrasing and a
REJECTED envelope gets a fixed declined response.
