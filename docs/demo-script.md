# CareLoop — demo script (~6 minutes)

Screen-by-screen walkthrough. Results depend on the current patient observations,
approval history and dish catalogue; rehearse with an isolated database first.
Start both processes before presenting.

## Start the stack

```bash
# terminal 1 — backend (repo root), port 8000
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --reload --port 8000
#   docs:   http://localhost:8000/docs
#   health: http://localhost:8000/healthz

# terminal 2 — frontend
cd frontend && npm run dev
#   app: http://localhost:5173  (Vite proxies /api -> :8000)
```

Open http://localhost:5173 — the Clinician review screen is the landing page.

## 1. Pick a CKD + HTN patient and generate the envelope (~1 min)

- On **Clinician review**, select **P0005** — 62 M, T2D + HTN + CKD stage 4,
  eGFR ≈ 25.
- Press **Generate proposed envelope**.

Say: *"The rule engine forward-chains 61 citable rules over this patient's
facts — diagnoses, labs, weight, meds — and proposes a nutrient envelope. Every
fired rule is kept in the trace below. Medication rules fire too: for a
patient on an ACE inhibitor you'll see potassium-monitoring cautions alongside
the nutrient constraints."*

Point at the constraint table: sodium max 2000 mg, protein 29.9–43.4 g (scaled
0.55–0.8 g/kg to his 54.3 kg), energy 1357–1900 kcal, potassium ceiling,
phosphate-additive exclusions.

## 2. Show the KDIGO-over-DASH sodium override (~1 min)

- In the **Fired-rule trace**, find **`DASH-2025-SODIUM-2300`** (priority 70).

Say: *"DASH would allow 2300 mg of sodium. But this patient has CKD stage 4,
and KDIGO 2024 — priority 90 — wins the conflict: the envelope carries KDIGO's
2000 mg ceiling instead. The loser is not deleted — its trace row is marked
`SUPERSEDED: superseded by CKD-2024-SODIUM-2000`, so the override is fully
auditable."*

Optionally open `/envelopes/ENV-P0005-001/explanation` (or
`http://localhost:8000/docs` → try it) to show the structured conflict list.

## 3. Approve (~15 s)

- Press **Approve**. Status badge flips to **APPROVED**.

Say: *"Live planning needs approved, scope-eligible, nonempty targets. Chat
does not quote pending targets as personal guidance, though informational views
remain available. Planning's gate is enforced as HTTP 409, not a convention."*

(Demo the gate if you like: press **Generate 7-day plan** for this patient
*before* approving on a fresh envelope and show the 409 "not approved" message.)

## 4. Generate a 7-day plan (~1.5 min)

- Go to **Meal plan**, pick **P0001** (T2D-only — produces a feasible plan on
  the demo pool). Generate and approve an envelope for P0001 first, then press
  **Generate 7-day plan**.

Say: *"The optimiser is a multi-objective NSGA-II over 21 meal slots — nutrient
deviation, preference, variety, cost — followed by main/optional-side composition
against the original aims. MAX ceilings and exclusions are hard; MIN floors and
TARGETs are soft. Any delivered plan has zero hard violations, but can still
miss a nutritional aim."*

- Open a day card: three meals, possibly including sides, and **Daily totals vs targets**
  bars — sodium under the 2300 mg ceiling, calories inside the range, etc.
- Back on P0005 (strict renal envelope), inspect feasibility and adequacy rather
  than promising a particular outcome. If no plan is found, show the reason and
  `infeasibility_status` (search exhaustion versus a proven single-dish limit).
  Say: *"Nothing unsafe is plated. A feasible plan can still miss original aims;
  any retained fallback floor adjustment is disclosed in `relaxed_constraints`."*

## 5. Chat: grounded, cited answers (~1 min)

- Go to **Chat**, pick P0005, ask:

  > **why is my sodium limit 2000?**

Say: *"The answer is assembled only from the versioned knowledge base — BM25
retrieval over rule chunks — plus his approved envelope numbers. It cites the
guidelines behind the number: KDIGO 2024 (the 2000 mg ceiling that won) and
AHA/ACC 2025 (the DASH 2300 that lost). No citation, no answer."*

- Then ask something out of scope:

  > **do I have kidney failure?**

Say: *"Diagnoses, medication changes — including 'should I stop taking
metformin?' — emergencies, pregnancy: the escalation filter refuses to answer
and hands it to a clinician instead. False positives are safe; false negatives
are not."*

## 6. The loop: log actual meals and see adherence (~1.5 min)

- Go to **Adherence**, pick **P0005**, and log **Chicken Rice (Hainanese)** for
  all three meals on dates covered by approval (search "chicken"). To demonstrate
  a trend, prepare at least five consecutive covered dates: keep breakfast and
  dinner fixed and increase the lunch serving quantity from 1 to 5 across them.
  If approval was only created today, collect future logs or use a prepared demo
  database; logging older dates does not backfill their approval coverage.

Say: *"This is the loop in CareLoop: the plan proposes, the patient logs
reality, and the system compares each logged date with the approval effective
on that date."*

- The **summary** shows per-day totals with **Over limit** rows: three chicken
  rice servings a day is about 3600 mg sodium against his 2000 mg KDIGO ceiling.
  Check the actual catalogue totals; increasing lunch servings increase exposure.
- The **trends** panel can flag worsening sodium exposure for the increasing,
  complete-day series above. Identical meals and quantities on every day give
  constant exposure, not a worsening trend.

Say: *"Hard ceilings are hard violations; MIN floors are soft aims reported
separately — same semantics as the optimiser. Dates without historical approval
remain unattributed. The latest envelope's informational notice is metadata;
it does not supply retrospective targets."*

## 7. Optional 30-second extras

```bash
curl -sS http://127.0.0.1:8000/kb/stats | jq          # versioned KB: 61 rules, 214 dishes
curl -sS http://127.0.0.1:8000/mining/trends | jq     # rising K+/PO4 flags, urgent first
curl -sS 'http://127.0.0.1:8000/mining/substitutions?dish_id=SG0001&k=3' | jq
```

## If the UI is unavailable

The same loop with curl (inspect the returned results during rehearsal):

```bash
P=http://127.0.0.1:8000
EID=$(curl -sS -X POST $P/rules/run -H 'content-type: application/json' \
      -d '{"patient_id":"P0005"}' | jq -r .envelope.envelope_id)
curl -sS -X POST $P/envelopes/$EID/approve -H 'content-type: application/json' \
      -d '{"approved_by":"Dr.Demo"}' | jq .status
curl -sS -X POST $P/plans -H 'content-type: application/json' \
      -d '{"patient_id":"P0005"}' | jq '{feasible, engine, violation_count, infeasibility_reason}'
curl -sS -X POST $P/chat -H 'content-type: application/json' \
      -d '{"patient_id":"P0005","message":"why is my sodium limit 2000?"}' | jq
curl -sS -X POST $P/chat -H 'content-type: application/json' \
      -d '{"patient_id":"P0005","message":"do I have kidney failure?"}' | jq
# adherence loop (upsert per slot; run in the server's local timezone)
for meal in breakfast lunch dinner; do
  curl -sS -X POST $P/adherence/log -H 'content-type: application/json' \
        -d "{\"patient_id\":\"P0005\",\"date\":\"$(date -I)\",\"meal\":\"$meal\",\"dish_id\":\"SG0001\"}" | jq
done
curl -sS "$P/adherence/P0005/summary?days=14" | jq '{informational_only, days_logged, aggregate: (.aggregate | {days_logged, hard_violation_days})}'
curl -sS "$P/adherence/P0005/deviation" | jq '.flags'
```

## Notes for the presenter

- Backend clinical state persists in SQLite across restarts. Use a temporary
  `CARELOOP_APP_DB` for an isolated demonstration.
- Rule content and trace are deterministic for unchanged patient facts; persisted
  proposals receive fresh identities/times. Observations and approval history can
  change the demo outcome. Adherence windows use the server's local date, not UTC.
- Dish nutrient values are curated estimates (`data/README.md`); present
  numbers as prototype-grade, not clinically validated.
