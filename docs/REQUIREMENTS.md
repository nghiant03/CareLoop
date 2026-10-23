# CareLoop requirements

Status: decisions from the user discussion, 2026-10-23. Not an implementation
completion report. Read with [data](DATA.md), [evidence](EVIDENCE.md), and
[evaluation](EVALUATION.md).

## Purpose and scope

Help clinicians review patient-specific nutrient goals and meal plans, generate
plans for patients, track reported meals, and answer nutrition questions with
evidence. This is a local academic prototype demonstrating all four technique
groups, not a clinically validated treatment system.

Initial population: ages 2+, generally healthy people, weight management,
children/adolescents, pregnancy/breastfeeding, and medical dietary restrictions.
Initial condition set: prediabetes/type 2 diabetes, hypertension, hyperlipidaemia,
and non-dialysis CKD. A condition label alone does not establish applicability of
every recommendation; stage, age, observations, medications, and exceptions may
matter. Support coexisting conditions and explicit unresolved conflicts.

Region: Singapore/SEA. Interface, extraction, and chat: English. Preserve the
established frontend visual style.

## Actors and access

- Patient: view approved targets/plans, set preferences, request plans and
  substitutions, log meals, and ask questions.
- Clinician: access every patient, enter/import patient data, review/edit/complete
  target proposals, approve targets and selected plans, review substitutions.
- Reviewer: submit sources, inspect extracted rules and original passages, edit,
  approve, publish, and retire rules; maintain food catalogue records.
- Use a demo role switcher. Actor names are attestations/demo labels, not verified
  identities. No individual clinician assignment is required.

## Evidence and rule lifecycle

1. Discover sources automatically within approved authoritative domains or accept
   reviewer-provided URLs, PDF uploads, and pasted text.
2. Extract candidate rules with supporting passages and source locations.
3. Review in structured fields: applicability conditions, nutrient/action, value,
   unit, exceptions, and supporting source side by side.
4. Allow one reviewer to approve, including their own edits. Support individual
   approval, source-level batches, and selected rules within a batch.
5. Resolve conflicting recommendations by applicability/explicit reviewer choice;
   unresolved conflicts prevent publication. Do not simply choose the strictest.
6. Explicitly publish an approved batch as a stable version.
7. Refresh sources on demand. Changes create new drafts with differences visible;
   the existing approved version stays active until publication or retirement.
8. Retire incorrect published rules: exclude from new proposals, flag affected
   targets, and retain history.

Rules can express numerical targets/limits, food exclusions, meal-timing advice,
and a requirement for clinician assessment. Qualitative guidance must not become
an invented numerical limit. Recommended intakes, ceilings, ranges, and additional
amounts are distinct concepts.

Audit: who changed what, when, why, and the supporting source, with revision
history. Discussion threads are not required. Source review and patient approval
are separate workflows.

## Patients and personalized targets

- Manual entry and documented CSV import for profiles and observations. No existing
  user-provided import format must be preserved.
- Select published recommendations using actual patient facts; calculate proposals
  where supported, and display their reasoning/citations.
- Missing information yields an incomplete proposal and targeted requests for
  required fields; identify recommendations that cannot yet be assessed.
- Clinicians can manually complete or override targets. Record these as clinician
  authored, not falsely sourced to the underlying guideline.
- Clinician approval is required before planning.
- Relevant changes to diagnoses, allergies, measurements, or published rules flag
  affected targets/plans for review. Do not silently change approved values.
- Existing plans remain viewable; new generation and substitutions are blocked
  while reassessment is pending. Newly recorded allergens flag affected meals.
- Newly approved target sets require new plans generated and approved against
  them; earlier plans remain historical.

Weight-goal recommendation (not separately confirmed in detail): let patients
express maintain/lose/gain preferences; use sourced energy estimation and clinician
approval. Use population-specific methods for children, pregnancy/breastfeeding,
and relevant complications, not blanket adult calorie deficits. Exact methods,
activity inputs, and supported weight-goal policies remain to be specified.

## Meal generation and approval

- User-selected duration: 1–7 days.
- Default schedule: breakfast, lunch, dinner, optional snack; user adjustable.
- Main workflow: system-generated plans. External-plan review was requested, but
  its input details and first-version priority remain less specified.
- Three alternatives emphasize (1) closest nutrient fit, (2) strongest preference
  match, and (3) greatest variety. Each must meet mandatory constraints to be usable.
- Patient dislikes are soft avoid-when-possible preferences. Vegetarian choices
  and allergies are mandatory. Egg and dairy inclusion are independently selectable.
- Patient requests generation; clinician approves the selected alternative.
- Substitutions re-evaluate affected plan totals and constraints and create a
  revised draft for clinician approval, not an immediate change to the active plan.
- If no compliant plan is found, explain blockers and show a clearly marked unmet
  draft if useful. A violating draft must not masquerade as an approved plan.
  Distinguish search failure from proven infeasibility.
- Prepared dishes with optional sides/fruit/drinks and sensible portion adjustments
  were recommended. Exact composition and portion policies remain data-dependent;
  the user did not select a fixed recipe-generation requirement.
- Budget and cooking time were not selected optimization objectives. Do not invent
  price/time data or add them as mandatory features.

Allergy recommendation: exclude a candidate when relevant ingredient/allergen
information is unresolved; dish-name inference is insufficient. Ingredient data
cannot establish vendor cross-contact practices. Exact completeness checks need
definition after source inspection.

## Catalogue and mining

Reviewers can correct categories, portions, ingredients, and allergen information,
with provenance and history. Nutrient/portion records used by historical plans
must remain interpretable when catalogue information is revised.

Use food-based nutrient clustering and substitution recommendations, not patient
behaviour mining as the main discovery technique. Find nutritionally similar,
meal-compatible alternatives, rank against approved targets/preferences, and show
differences. Similarity is not itself a suitability decision; apply the same rules
and approval workflow as planning. Algorithm choice is open and must be evaluated
against simpler non-clustered recommendations.

## Meal logging and patient questions

- Default: confirm planned meal as eaten; choices include as planned, changed
  quantity, replaced, or skipped.
- Also support independent food entry with portions.
- Preserve distinction between a skipped meal, unlogged meal, and complete day.
- Chat explains approved plans/targets, answers general nutrition questions with
  citations, suggests substitutions, and explains recorded meals against targets.
- Diagnosis and medication-change requests are directed to the clinician.
- Suggestions follow plan approval rules. Direct chat-driven saving of arbitrary
  plan changes was not selected as an initial requirement.
- Use hosted LLM for language/extraction; deterministic calculation/checking for
  nutrient arithmetic and enforceable constraints.

## Deployment and implementation choices

Single local deployment with PostgreSQL and Docker Compose. No old patient-record
migration is required. Remaining external cleanup is tracked in [implementation status](IMPLEMENTATION.md).

Engineering choices are documented in [architecture](ARCHITECTURE.md) and the
workflow contracts; they are not additional user-approved requirements. Hosted
model selection, reference formulas, measurable latency targets, and external-plan
input remain open.
