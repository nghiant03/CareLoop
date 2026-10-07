# CareLoop Frontend

Placeholder for the clinician + patient single-page app.

**Status:** Week 1 stub — no code yet. Planned stack (Week 3, PLAN.md §7):
**React + Vite + Tailwind CSS**, two roles (clinician review screen, patient
meal screen, RAG chat).

## Planned screens
- Clinician: patient list, proposed envelope review (targets/exclusions +
  fired-rule trace with guideline citations), approve / edit / reject.
- Patient: 7-day meal plan, plain-language "why this meal" explanations.
- Chat: citation-required RAG assistant with escalation to a clinician.

## Approval gate
The UI must only render approved constraints downstream of the review screen.
Approval state comes from the backend (`POST /envelopes/{id}/approve`); the API
returns `409 {"error": "envelope_not_approved"}` for any non-APPROVED envelope.

_Scaffolding (`npm create vite`, Tailwind config, API client) lands in Week 3._
