# CareLoop

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Clinician-first: clinicians reviewing patients, nutrient envelopes and evidence.
Patient meal planning, chat and adherence remain supported. Knowledge reviewers
and operators discover evidence, create or clone drafts, edit rules and catalogue
records, review exact revisions and publish reviewed knowledge.

## Product Purpose

Turn approved nutrient envelopes into Singapore meal plans, assess logged-meal
adherence and answer nutrition questions with citations.

## Operating Context

Clinical review across the existing application, with a separate operator-only
local knowledge workspace and API replacing the knowledge CLI. Deployment setup
is automatic; there are no login/admin accounts or backup feature.

## Capabilities and Constraints

- Approval is a workflow state, not proof of human clinical review. Academic demo
  auto-approval must remain disclosed.
- Knowledge drafts are unpublished. Review decisions
  are bound to a revision and do not publish or activate knowledge. Edits append
  a revision and require a new independent review. Publication requires an
  independent approving review of that exact revision and explicit confirmation;
  it freezes the revision, but activation still requires a controlled restart.
- Published dish IDs must retain their historical meaning.
- Create drafts from executable rulebook and catalogue JSON, or clone published
  releases. Discovery reports are review-only candidates, not executable rules.
- Discovery accepts multiple PDF, HTML, Markdown or text guidelines without
  source manifests, hash registration or guideline-specific code. Uploads are
  temporary, limited to 10 files and a 32 MiB encoded request; no patient records.
- Discovery is LLM-only and provider-neutral. Provider selection is deferred;
  extraction is unavailable until an adapter is connected, with no static-pattern
  fallback. The editable external prompt lives at
  `backend/knowledge/prompts/discover_rules.md`; workspace edits apply only to the
  current extraction and do not overwrite that file.
- MAX ceilings and exclusions are hard constraints; MIN and TARGET are soft aims.
- Preserve evidence, provenance, stale-revision protection and existing actions.

## Brand Commitments

CareLoop; clear, clinical, factual language. Prioritize readable data and decisions.

## Evidence on Hand

README.md, docs/ARCHITECTURE.md and docs/KNOWLEDGE.md describe the actual contracts.
Existing screens and regression tests supply workflow evidence.
