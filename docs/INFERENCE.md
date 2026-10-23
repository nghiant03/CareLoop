# Hosted inference

Hosted models support source-rule extraction and cited education. Numerical
checking, optimization, and clustering run locally.

## Configuration

Set provider-neutral variables in the Git-ignored `.env` file:

```dotenv
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=your-key
```

The shared `inference.py` client loads `.env` from the working directory; process
environment values take precedence. Compose passes these two variables to the API
without copying `.env` into images. Keys are excluded from configuration reprs,
stored request metadata, and provider error messages.

The supplied endpoint is user-confirmed unmetered. Provider-reported usage and cost
are retained as telemetry; no energy values are inferred from token counts.

## Application integration

- `GET /api/inference/models` discovers model IDs. Extraction requests default to
  `glm-5.3`; an explicit `model` overrides it. Shared request builders resolve a
  `None` model to the same default for extraction and cited answers.
- `inference.py` handles OpenAI-compatible `/models` and `/chat/completions` requests.
  Calls have timeouts, output/response limits, no automatic retries, and no redirects.
- `evidence/extraction.py` owns extraction prompts, schema/predicate validation, run
  persistence, and draft creation. See [evidence](EVIDENCE.md#hosted-rule-extraction).
- `answers.py` defines cited-education prompts and output validation. `chat.py`
  adds approved patient context, published-quotation retrieval, persisted turns,
  and stale-context checks. Models select source IDs;
  the server attaches their original text as quotations. This verifies source
  identity, not semantic support for every generated claim.

There is no inference CLI. API endpoints and development notebooks use these shared
Python modules directly.

## Patient conversation

The patient workspace `/patient/nutrition-questions` uses:

- `GET /api/patients/{id}/chat/context`: current patient revision, approved target
  revision, facts, target items, and evidence generation, or an explicit not-ready reason.
- `POST /api/patients/{id}/chat`: patient actor/reason, request UUID, question (up to
  2,000 characters), and the expected `patient_revision`, `target_id`, `target_revision`.
  Optional model/generation overrides remain supported; defaults are GLM 5.3,
  JSON mode, high reasoning, and 8,192 output tokens.
  Optional `workflow` selects `plan_id`, `logged_on` (ISO date), and `substitution`
  (`day`, `slot`, `item`, and 1–100 unique candidate `food_ids`). Substitutions
  require a selected plan; no catalogue-wide pool or meal identity is inferred.
- `GET /api/patients/{id}/chat`: newest-first paginated history (`limit`/`offset`).
- `GET /api/patients/{id}/chat/{request_id}`: saved pending/completed/failed outcome.

Only current clinician-approved targets supply patient context. The request snapshots
their pinned facts and items, up to eight lexically matched active published rule
quotations, and three completed exchanges from the identical target/patient/evidence
and selected-workflow snapshot. Draft and retired evidence are excluded. Record citations are labelled
separately from published evidence; original text is attached in code. Display names
and free-text patient provenance are not sent. Null facts remain unknown.

The model may explain existing approved targets but cannot create or change them.
Diagnosis, medication changes, and requests for new treatment go to the clinician.
`chat_workflows.py` connects the existing deterministic services:

- Plans must belong to the patient and be approved/current against the selected
  target revision. Per-day sources include planned portions and checked daily totals.
- Intake sources include the selected date's reported entries, revision IDs, unknown
  nutrients, day completeness, and planned/unlogged item states when a plan is selected.
  Target comparisons are calculated by the logging service; the model does no new arithmetic.
- Substitution sources come from the existing nearest-neighbour retrieval and whole-plan
  checker. Returned suggestions retain food revisions, portions, nutrient differences,
  and explicit approval-required/search-limit flags. The UI can request a replacement
  draft through the existing substitution endpoint; a chat answer never mutates a plan.

The `patient-chat-v2` prompt distinguishes partial days from deficits, unknown nutrients
from zero, and unlogged items from skipped meals. It explains only the selected dates
and records and asks for attachments when needed. Free-text intake notes are not sent.
The combined reference limit is 120,000 characters, with 10,000 per quotation;
oversized requests fail explicitly rather than silently dropping records.

Migration `008_patient_chat.sql` retains requests, context, raw responses, results,
and audit events. Pending requests commit before inference; no connection or lock
is held during network calls. Identical request UUIDs return the saved outcome;
changed inputs return 409. Patient context, evidence generation, selected plan status,
intake revisions/completeness, and candidate food revisions are checked again
after inference, and a changed snapshot produces a failed run rather than a current
answer. The UI labels older snapshots as historical on refresh. Failures and unknown
outcomes are retained without automatic retry. Public history omits provider payloads
and returns `stale` plus the original workflow selection. Freshness checks use saved
revision stamps without repeating inference or substitution search. Existing JSONB
storage holds the new snapshots; no new migration is needed.

Lexical retrieval and source-ID validation do not establish semantic support for
every generated claim. Broader source/question evaluation remains necessary.

## Output format and reasoning

Extraction requests accept an optional `generation` object:

```json
{
  "response_mode": "json_schema",
  "reasoning_effort": "high",
  "max_tokens": 8192,
  "temperature": 0
}
```

`json_schema` is the default. The client sends `response_format` with `strict: true`,
all properties required (nullable where applicable), and `additionalProperties: false`.
`json_object` explicitly requests JSON mode without provider-side schema enforcement.
Both modes undergo the same local JSON Schema, Pydantic, and domain validation.
Unsupported parameters fail visibly; no retry silently drops reasoning or changes format.
A successful response does not establish server-side schema enforcement. Both
formats receive explicit schema instructions in the prompt and local validation.

Defaults are 4,096 output tokens, temperature 0, and omitted `reasoning_effort`.
The token cap can be set from 1 to 8,192; reasoning can consume that budget. A null
temperature omits that parameter. Supported reasoning levels depend on the model;
the experiment explicitly uses `high` for both selected models. Refusals, truncation,
JSON errors, schema errors, and domain/grounding errors are distinguished internally.
The full requested schema/settings are retained with each run.

Prompts separate instructions from evidence, define predicate types, explain
unrepresentable populations with examples, and prohibit unsourced age cutoffs and
evidence-grade interpretations. Missing guidance prompts abstention. Source-ID
citations avoid asking models to reproduce PDF whitespace. These techniques do
not replace review of clinical meaning or source context.

References: [Chat Completions compatibility](https://hyper.charm.land/docs/api/openai-chat-completions.md),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Z.ai JSON-mode guidance](https://docs.z.ai/guides/capabilities/struct-output).
Z.ai documents `json_object` with structure/field requirements in system messages
and client-side validation; that does not establish native strict-schema enforcement.

## Model selection experiment

[notebooks/model_selection.ipynb](../notebooks/model_selection.ipynb) contains four
workflow cases using a public KDIGO passage: extraction, cited explanation,
missing potassium guidance, and medication referral. Instructions and schemas
are consistent in every request.
It imports the application prompts
and validators, stores requests/responses outside Git, resumes without repeating
saved calls, and reports from saved responses without credentials or network access.
Live execution is disabled by default; use a kernel with CareLoop installed.
Non-sensitive result summaries are saved inline in this single notebook; raw
responses and account telemetry remain in the external cache.

The experiment compares Qwen 3.8 Max and GLM 5.3 with explicit high reasoning and
equal 8,192-token caps. JSON/schema conformance, source grounding, and bounded
content checks are scored separately. Each workflow runs once per model in both
`json_object` and `json_schema` modes, with identical prompts, temperature 0,
and local validation. The sixteen requests test ordinary task performance;
they do not measure adversarial schema enforcement. Generated response text is
retained inline for inspection. GLM 5.3 is the selected application default;
generation settings remain independently configurable.
The aligned run produced schema-valid JSON in all 15 completed requests. In JSON
mode, Qwen passed 4/4 bounded content checks and GLM 3/4; in JSON Schema mode,
Qwen passed 3/3 completed cases and GLM 3/4. GLM's missing-potassium answer added
the source's protein quantity and grade without citations in both modes. The
quantity was sourced, not invented, but violated the abstention instruction.
One Qwen JSON Schema extraction request was interrupted by the notebook host
timeout; its outcome remains unknown and is excluded from completed-case scores.
Cached notebook execution verified the report without further provider calls.

### Abstention prompt comparison

A 21-call GLM JSON-mode comparison held source text and generation settings fixed
across v2, v3, and v4 answer prompts. Each variant received three potassium trials,
missing phosphorus and energy questions, a supported protein question, and a
medication-referral question. All outputs passed JSON/schema validation.

V2 added uncited quantities/grades in all five missing-evidence trials. V3's
answerability branch and stopping rule removed those details, but three potassium
answers still appended an unrelated source-topic aside. V4 adds a final abstention
sentence template: all three potassium responses were clean, while the phosphorus
response still added a qualitative protein aside. Across the seven trials, full
content/focus checks passed 2/7 for v2, 4/7 for v3, and 6/7 for v4. Supported answers
and clinician referrals passed for every variant.

The application uses v4. It fixed the observed uncited-quantity issue in this small
test, but did not eliminate every irrelevant aside. The focus check was added after
manual review of v3 and applied to every variant; these are development results.
Frozen prompts and all responses are retained in the notebook, with live calls
disabled by default. Repeated temperature-zero outputs do not establish broad reliability.
This experiment is not a held-out evaluation or clinical validation. Broader source
coverage, extraction accuracy, citation support, and patient-question benchmarks
remain in the [evaluation plan](EVALUATION.md).

A local LLM is not required. The laptop has a 5050 GPU; other hardware details remain
unmeasured.

## Frozen system comparison

The notebook's system-evaluation section uses static team-labelled references and
the reusable `careloop.evaluation` functions. Four endpoint-catalogue families are
selected: GLM 5.3, Qwen 3.8 Max, DeepSeek V4 Pro (`deepseek-v4-pro-0813`) and Kimi K3.
All receive the same application prompts, JSON mode, high reasoning request,
temperature zero and an 8,192-token cap. The 168 planned calls comprise 14 extraction
passages, 20 questions and eight evidence-removal ablations per model.

KDIGO is development-only because of the earlier prompt experiment. WHO carbohydrate
and HealthHub RDA are held out. Raw records retain failures, usage and latency;
model-blinded team assessment is separate from bounded automatic checks. See
[evaluation](EVALUATION.md) for source splits, scope and reproduction. This comparison
does not automatically change the application's default model.
