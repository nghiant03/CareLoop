# CareLoop — 5-minute demo script

Screen-by-screen walkthrough. Every command below has been run against the
current codebase. Start both processes first.

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

Say: *"The rule engine forward-chains 52 citable rules over this patient's
facts — diagnoses, labs, weight, meds — and proposes a nutrient envelope. Every
fired rule is kept in the trace below."*

Point at the constraint table: sodium max 2000 mg, protein 29.9–43.4 g (scaled
0.55–0.8 g/kg to her 54.3 kg), energy 1357–1900 kcal, potassium ceiling,
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

Say: *"Nothing downstream — no meal plan, no patient view, no chat numbers —
can use these constraints until a clinician approves them. That's a hard gate
in the API, enforced as HTTP 409, not a convention."*

(Demo the gate if you like: press **Generate 7-day plan** for this patient
*before* approving on a fresh envelope and show the 409 "not approved" message.)

## 4. Generate a 7-day plan (~1.5 min)

- Go to **Meal plan**, pick **P0001** (T2D-only — produces a feasible plan on
  today's 190-dish pool), press **Generate 7-day plan**.

Say: *"The optimiser is a multi-objective NSGA-II over 21 meal slots — nutrient
deviation, preference, variety, cost — with the approved limits as hard
constraints. It guarantees zero hard-constraint violations: repair, then greedy
fallback."*

- Open a day card: three dishes per day, and the **Daily totals vs targets**
  bars — sodium under the 2300 mg ceiling, calories inside the range, etc.
- Back on P0005 (strict renal envelope), the plan endpoint returns an explicit
  **infeasibility diagnosis** (`feasible=false`, reason disclosed) instead of a
  violating plan — say: *"when the dish pool can't satisfy the envelope, the
  system says so rather than plating an unsafe plan; and unreachable guideline
  floors are lowered with a `relaxed_constraints` disclosure, never silently."*

## 5. Chat: grounded, cited answers (~1 min)

- Go to **Chat**, pick P0005, ask:

  > **why is my sodium limit 2000?**

Say: *"The answer is assembled only from the versioned knowledge base — TF-IDF
retrieval over rule chunks — plus her approved envelope numbers. It cites the
guidelines behind the number: KDIGO 2024 (the 2000 mg ceiling that won) and
AHA/ACC 2025 (the DASH 2300 that lost). No citation, no answer."*

- Then ask something out of scope:

  > **do I have kidney failure?**

Say: *"Diagnoses, medication changes, emergencies, pregnancy — the escalation
filter refuses to answer and hands it to a clinician instead. False positives
are safe; false negatives are not."*

## 6. Optional 30-second extras

```bash
curl -sS http://127.0.0.1:8000/kb/stats | jq          # versioned KB: 52 rules, 190 dishes
curl -sS http://127.0.0.1:8000/mining/trends | jq     # rising K+/PO4 flags, urgent first
curl -sS 'http://127.0.0.1:8000/mining/substitutions?dish_id=SG0001&k=3' | jq
```

## If the UI is unavailable

The same loop with curl (all verified):

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
```

## Notes for the presenter

- Backend state (envelopes, traces, created patients) is process-local; a
  restart resets it, so re-run `/rules/run` after restarting.
- Rule engine output is deterministic — the same patient always yields the same
  envelope and trace, so this demo reproduces exactly.
- Dish nutrient values are curated estimates (`data/README.md`); present
  numbers as prototype-grade, not clinically validated.
