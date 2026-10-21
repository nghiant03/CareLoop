# CareLoop

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Clinician-first: clinicians reviewing patients, nutrient envelopes and evidence.
Patient meal planning, chat and adherence remain supported. Knowledge reviewers
inspect proposed rules and catalogue records before a draft-level decision.

## Product Purpose

Turn approved nutrient envelopes into Singapore meal plans, assess logged-meal
adherence and answer nutrition questions with citations.

## Operating Context

Clinical review across the existing application, with a separate operator-only
knowledge review deployment. The user requested a consistent redesign across all
screens and a rebuilt Knowledge Review workspace.

## Capabilities and Constraints

- Approval is a workflow state, not proof of human clinical review. Academic demo
  auto-approval must remain disclosed.
- Knowledge drafts are unpublished and not for clinical use. Review decisions
  are bound to a revision and do not publish or activate knowledge.
- Reviewer names are attestations, not authenticated identities.
- MAX ceilings and exclusions are hard constraints; MIN and TARGET are soft aims.
- Preserve evidence, provenance, stale-revision protection and existing actions.

## Brand Commitments

CareLoop; clear, clinical, factual language. Prioritize readable data and decisions.

## Evidence on Hand

README.md, docs/ARCHITECTURE.md and docs/KNOWLEDGE.md describe the actual contracts.
Existing screens and regression tests supply workflow evidence.
