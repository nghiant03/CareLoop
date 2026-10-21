# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary audience (confirmed 2026-10-21): academic demo / evaluation audience —
evaluators and researchers walking the full workflow end-to-end. Both on-screen
roles matter equally: the clinician who reviews and approves nutrient envelopes,
and the patient who receives meal plans, logs adherence, and asks nutrition
questions.

## Product Purpose

CareLoop plans Singapore meals, tracks logged-meal adherence, and answers
nutrition questions with cited evidence for T2D, hypertension, and CKD
stages 3–4. Planning and personal targets require an APPROVED nutrient
envelope. Success for the demo surface: an evaluator can see, within minutes,
how an envelope moves from proposal to approval to plan to adherence feedback,
with rule traces and citations visible at each step.

## Positioning

The mechanism a neighboring product could not truthfully copy: a governed
approval lifecycle for nutrient envelopes (propose → approve/edit → version,
with scope exclusions, hard ceilings vs. soft floors, and durable rule traces)
coupled to planning, adherence attribution against approval coverage, and
citation-grounded chat — all pinned to the same published knowledge snapshot.

## Operating Context

Academic showcase. Defaults to `CARELOOP_APPROVAL_MODE=auto`: eligible new
proposals are auto-approved and must be clearly disclosed as **demo, not
clinically reviewed**; `clinician` mode demonstrates manual review. Edits
always invalidate approval in both modes. Runs against PostgreSQL with
fixture or published-release knowledge. Screens: Clinician review, Review
queue, What-if simulations, Meal plan, Chat, Adherence.

## Capabilities and Constraints

- Only APPROVED envelopes authorize live planning and personal target guidance.
- Hard constraints are MAX ceilings and exclusions; MIN floors and TARGETs are
  soft; relaxed floors must be disclosed.
- Scope-rejected patients must remain excluded; the demo UI must disclose
  auto-approval.
- Chat must retain grounding, citation, refusal, and escalation behavior.
- Frontend: React + Vite + Tailwind CSS 4, react-router, Vitest tests.
- Redesign latitude (confirmed 2026-10-21): copy may be refined and layout may
  be restructured; clinical facts, numbers, disclosure obligations, and
  workflow behavior must stay truthful and functional.

## Brand Commitments

Name "CareLoop". No other confirmed brand assets or visual constraints.

## Evidence on Hand

Rich domain content in-repo: rule traces, constraint tables, adherence
analytics, cited chat answers, demo script (`docs/demo-script.md`), user
guides. No marketing claims, testimonials, or customer evidence exist —
future work must not fabricate them.

## Product Principles

1. Approval state is sacred: every screen makes envelope status and its
   provenance legible.
2. Evidence over assertion: traces, citations, and disclosure are first-class
   UI material, not footnotes.
3. Hard limits vs. soft aims are visually distinguishable everywhere.
4. The demo workflow reads end-to-end: an evaluator can follow one patient
   from proposal to plan to adherence.
