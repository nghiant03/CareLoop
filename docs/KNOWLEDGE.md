# Knowledge workspace and published knowledge

Knowledge operations use a web UI and HTTP API. The operator knowledge CLI has
been removed. Clinical and knowledge state remain in separate PostgreSQL databases.
Schema preparation belongs to the automatic deployment `setup` task, not runtime.

## Open the workspace

Start the root Compose stack normally and visit
**http://127.0.0.1:8080/knowledge-review**. The default deployment mode is `review`:
it starts with an empty authoring journal, without a preselected draft or release.
No manual database initialization command or operator UID/GID is required.

If returning from clinical mode, select `CARELOOP_DEPLOYMENT_MODE=review`, unset
`CARELOOP_KNOWLEDGE_RELEASE`, and restart backend/frontend. A workspace cannot
select a live release simultaneously. Clinical routes are disabled in this mode.

## Security boundary

The workspace API runs only in operator mode, not alongside clinical routes.
Mutations require the process-bound `X-Review-Token` obtained from `GET /knowledge`.
Cross-origin mutations and unexpected Host headers are refused.

Local PostgreSQL accepts passwordless connections using its built-in `postgres`
role. There is no custom `careloop_admin` account on fresh installations. Existing
volumes may retain their original role; see [POSTGRES.md](POSTGRES.md).

## Automatically propose evidence-backed rules

Open **Discover sources**. Discovery is LLM-based; there are no hard-coded KDIGO
recommendation patterns and no static fallback. A concrete provider has deliberately
**not been selected**. Until one is connected, the UI disables extraction and the
API returns HTTP 503 without attempting a model call. No API key or provider-specific
environment variable is required just to run the workspace.

### Add another source

1. Obtain an appropriately licensed guideline from its publisher. Save a PDF,
   HTML, Markdown or UTF-8 text file outside the checkout.
2. In **Discover sources**, choose **Add guideline files**. Select multiple files,
   or add more in another selection. ADA, DASH, KDOQI and other guidelines do not
   require new Python adapters or an allowlist entry.
3. Optionally enter the original publisher URL next to each file. The server does
   not download URLs or read arbitrary host filesystem paths from requests.
4. Inspect or edit **Extraction instructions**, then extract once a provider adapter
   is available. Up to 10 sources and a 32 MiB encoded request are accepted.
5. Inspect every candidate against the original source before authoring executable
   rule changes. Candidates never become live knowledge automatically.

**No manifest registration, file hash calculation or hash validation is part of
discovery.** File-format/readability checks and source-quote matching remain.
PDFs use Poppler's `pdftotext` (included in the backend image); HTML/text are read
directly. Scanned PDFs need separately prepared readable text; no OCR is implied.

The backend's `DiscoveryClient` protocol exposes
`extract_candidates(instructions=..., source_text=...) -> dict`. A future provider
adapter owns transport, credentials and response parsing. The core service is
callable from Python and the API; it is not coupled to a CLI or to OpenAI.

### Editable prompt and evidence

Default instructions live in **`backend/knowledge/prompts/discover_rules.md`**,
not in Python. The workspace loads this resource and sends any per-request edits
as `instructions`. Edits do not change the server file. Direct Python callers can
use `load_discovery_prompt(path)` for an external prompt file.

Discovery sends overlapping bounded text chunks to the selected adapter. It
accepts recognized nutrient/constraint identifiers, finite positive values, an
explicit unit/body-weight basis and quotations present in the supplied text.
Repeated identical chunk results are deduplicated. Reports retain source filenames,
optional URLs, exact extracted-text spans, PDF page numbers, model metadata,
instructions, source populations, model-reported caveats and baseline-rule comparisons.
API uploads are temporary; the returned report is not written to either database.

Every candidate remains `NEEDS_REVIEW`, with `executable_rule: null` and
`automatic_activation_allowed: false`. The report format is now schema version 2;
old schema-1 reports remain preserved files, not automatic import inputs. Optional
Python report writing uses fresh external run directories, not content hashes,
and never overwrites existing operator work.

A matching quote proves text presence, **not** correct interpretation. Review
numbers, units, sodium versus salt, per-kg versus daily quantities, negation,
population, strict inequality, evidence grades and exceptions in the full document.
Extraction is non-exhaustive and nondeterministic. Model caveats are unverified
suggestions. NHANES/MIMIC associations and food-composition values are not automatic
prescribing evidence. MIN/TARGET are soft aims; MAX allows equality and is a hard
ceiling only after an explicit clinical mapping decision.

## Create, edit and review drafts

- **Create draft:** load or paste a complete CareLoop `rules.json` and dish
  catalogue JSON; supply a draft ID and author label. External fixtures can be
  initial inputs but are not clinical approval. Discovery reports are not rulebooks.
- **Open a draft:** inspect searchable rules, exact evidence, conditions/actions,
  authoring blockers, catalogue provenance and event history. Compare a selected
  rule against an earlier revision.
- **Edit & publish:** edit the complete documents and save a new revision with
  a change rationale. Revisions are append-only; reviews do not carry forward.
- **History & decision:** an independent reviewer label records approve/reject
  for the exact displayed revision and confirms complete-revision review.
- **Publish revision:** supply an unused release ID and publication rationale.
  The latest revision requires an approving review. Select the published release
  and restart the deployment to activate it.
- **Clone release:** start another draft from a published release. Published
  drafts are immutable.

Every mutation uses the expected revision and is transactional. Stale operations,
self-review, duplicate decisions and identity collisions are refused. Successful
content/review/publication writes append audit events in the same transaction.
Server validation checks schema, DSL compilation, representative scope cases
and catalogue fields.

**Published dish IDs preserve historical meaning.** Keep their nutrient values,
portion, category, ingredients and tags unchanged and retain old IDs for saved
plans and logs. Corrections require new IDs. There is no catalogue deactivation
or deletion feature. No operation here deletes existing journal records.

## HTTP API

The browser uses `/api` as a proxy prefix; application routes below omit it.
Interactive documentation is available at `/api/docs` in operator mode.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/knowledge` | Draft list, request token, provider availability and prompt |
| POST | `/knowledge/discover` | Uploaded sources and optional instructions → review-only report |
| POST | `/knowledge/drafts` | Create a draft from rule/catalogue documents |
| GET | `/knowledge/drafts/{id}?revision=N` | Current or historical documents and event history |
| PUT | `/knowledge/drafts/{id}` | Append an edited revision |
| POST | `/knowledge/drafts/{id}/review` | Independent revision-bound decision |
| POST | `/knowledge/drafts/{id}/publish` | Publish an approved revision; never activate it |
| GET | `/knowledge/releases/{id}` | Read a published rulebook/catalogue |
| POST | `/knowledge/clone` | Clone a published release into a new draft |

Review/publication requests require an explicit `confirmed: true`. Old
`/knowledge-review/*` inspection endpoints are replaced by these workspace routes;
the browser entry path `/knowledge-review` remains unchanged.

## Activate a published release

Select `CARELOOP_DEPLOYMENT_MODE=published` and an explicit
`CARELOOP_KNOWLEDGE_RELEASE`, then restart backend/frontend. All runtime consumers
pin the same published snapshot until restart. Missing, draft, corrupt or
incompatible releases block startup; there is no fixture fallback or implicit
latest selection. Publication alone does not hot-reload caches.

Live envelopes/plans and evaluation artifacts retain release IDs and source hashes.
Release-integrity checks are separate from discovery and remain unchanged.
Legacy snapshots retain their embedded traces; no provenance is fabricated for them.
Older binaries may reject newer envelope fields, and an older release may lack dish
IDs referenced by current state. Selecting a previous release is not automatically
a safe rollback. Preserve databases, released evidence and historical records.
