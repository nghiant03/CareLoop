---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/index.css","frontend/src/components","frontend/src/screens"]
---

# Surface brief — whole CareLoop web app

Primary target: `frontend/src/App.tsx`. Related: `frontend/src/index.css`, `frontend/src/components/*`, `frontend/src/screens/*`.

- Mode: Operate. Audience: academic demo/evaluation — evaluators walk the full workflow end-to-end; clinician and patient roles both matter.
- Job: make the governed approval lifecycle (proposal → approval/edit → plan → adherence) and its evidence apparatus (rule traces, citations, disclosures) legible at a glance.
- Untouchables: clinical facts, numbers, disclosure obligations (auto-approval disclosure), workflow behavior, all tests green. Copy may be refined; layout may be restructured.

## Direction contract

THESIS: The UI is the laboratory report for a clinical nutrition trial. Every nutrient value sits inside its reference range, every approval is a verified-result block, every screen opens with a specimen-label strip. It refuses the rounded-card SaaS dashboard the incumbent wears.

OWN-WORLD: Paper-white ground (#FBFAF6), ink (#17140F), hairline rules (#E3E0D3), panel tint (#F4F2EA). State hues only: flag red (#B3352B), caution amber (#9A5B12), verified green (#1F6F4A), line blue (#1D4ED8) for interactive focus. Type: Public Sans for text/UI (workhorse grotesque, true tabular figures), Roboto Mono for data values, report codes, IDs, and microcopy labels (uppercase, tracked). Components: squared or 2px-radius corners, 1px hairline borders, no drop shadows; hierarchy carried by weight, scale, and rules — never by shadow.

STORY: The evaluator opens any screen and reads a working clinical report: masthead with report codes; patient roster; the selected envelope as an analyte panel — each constraint a row with its value plotted on a reference-range bar, hard ceilings as solid red termini, soft targets as hollow markers, flags in a dedicated column; approval as a bordered verified block with mono ID and revision; rule traces as annotation apparatus beneath.

FIRST VIEWPORT (Clinician review): masthead (wordmark "CareLoop", mono report code strip, nav as report-section tabs with the active section underlined in ink); below, a two-column report sheet — patient roster column (mono IDs, flag chips) and the selected envelope report: header block (patient name, mono IDs, verified block), constraint table with range bars, approval actions in a ruled footer.

FORM: Clinical laboratory report — grounded candidate #1 by resonance; the roll (seed key e87c7105) assigned #4 (MRT network map) and the user locked this pick card instead. Raises folded in from declined challengers: one persistent status axis per screen (specimen strip carries status), magnitude-by-scale hierarchy (severity = weight/size; hue reserved for state), expressed grid (hairline column rules in dense tables), focus-dimming (selection lifts, neighbours mute).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
