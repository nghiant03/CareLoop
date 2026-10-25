# Application structure

Implementation decision, 2026-10-23: one Python application, one PostgreSQL
database, and a workflow-oriented package layout. These are engineering choices,
not additional product requirements.

## Architecture diagrams

These views use the **C4 model's progressive zoom**: a container/component overview,
then algorithm and workflow detail. Mermaid flowcharts keep the diagrams editable
and renderable in Markdown. The detailed flows complement C4 rather than claiming
to be formal C4 deployment diagrams. They describe the implemented application.

1. [System overview](#system-overview)
2. [Decision automation](#decision-automation)
3. [Resource optimization](#resource-optimization)
4. [Knowledge discovery and mining](#knowledge-discovery-and-mining)
5. [Cognitive techniques: guideline extraction](#cognitive-techniques-guideline-extraction)
6. [Cognitive techniques: patient chat](#cognitive-techniques-patient-chat)

**Notation:** arrows show requests or data dependencies; dashed arrows show
reassessment or external inference. Purple nodes name computational techniques;
orange nodes mark human review/approval. Labels carry the meaning independently
of color. Database cylinders denote persistent records.

### System overview

One browser frontend, one modular Python backend, and one PostgreSQL database.
The four technique groups are modules inside the backend, not separate services.

```mermaid
flowchart TB
    users["Patient · Clinician · Evidence reviewer"]
    web["Role-specific workflows · single API client"]
    users --> web
    subgraph backend["CareLoop"]
        api["HTTP API /api<br/>Demo-role guards · revision checks"]
        decision["Knowledge-based rules · Constraint checking "]
        optimize["Heuristic beam search ·  Meal-plan alternatives"]
        mining["K-means clustering · Content-based food recommendations"]
        language["LLM guideline extraction ·  Evidence-grounded patient chat"]
        records["Domain records and audit"]
        api --> decision
        api --> optimize
        api --> mining
        api --> language
        language -->|"Extracted drafts for review"| decision
        decision -->|"Current approved targets and shared checks"| optimize
        decision -->|"Current approved targets and shared checks"| mining
        mining -->|"Checked substitution suggestions"| language
        decision --> records
        optimize --> records
        mining --> records
        language --> records
    end
    web -->|"HTTP / JSON"| api
    records --> db[("PostgreSQL<br/>Immutable revisions · approval records · audit events")]
    sources["Clinical guideline documents<br/>Public food datasets"] -->|"Acquisition and adapters"| records
    language -.->|"OpenAI-compatible inference client"| llm["External hosted LLM provider"]
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    class decision,optimize,mining,language technique;
```

The API uses local demo role labels, not authenticated identities. Numerical
reasoning, search, clustering, and checking execute locally. Hosted inference is
used for extraction and language generation. All writes and their audit events
commit together; provider calls occur outside database locks.

### Decision automation

**Techniques: knowledge-based rules, three-valued reasoning, constraint checking,
and human approval workflows.** Executable rules use typed predicates rather than
free-text interpretation at planning time.

```mermaid
flowchart TB
    rules[("Published, non-retired rule revisions<br/>Predicates · exceptions · actions · citations")]
    facts[("Patient fact revision<br/>Known values and explicit unknowns")]
    evaluate["KNOWLEDGE-BASED RULE ENGINE<br/>Typed predicates and condition aliases<br/>"]
    rules --> evaluate
    facts --> evaluate
    evaluate --> result{"Applicability and exceptions"}
    result -->|"Any applicability false, or any exception true"| exclude["Not applicable / excluded"]
    result -->|"Otherwise missing facts or unsupported predicates"| incomplete["Incomplete evaluation<br/>Named facts or rule corrections required"]
    result -->|"All applicability true, all exceptions false"| classify["Separate numeric targets,<br/>required assessments, optional guidance"]
    classify --> proposal["Target proposal with source snapshots<br/>Explicit per-kg calculations where supported"]
    proposal --> clinician["CLINICIAN REVIEW<br/>Resolve competing targets and assessments<br/>Enter or explicitly adopt numeric energy range"]
    incomplete --> correct["HUMAN CORRECTION<br/>New patient or rule revision, then re-propose"]
    correct --> evaluate
    clinician --> gate{"APPROVAL CHECKS<br/>Current revisions · no blockers<br/>Positive daily energy range in kcal/day"}
    gate -->|"Unresolved"| clinician
    gate -->|"Pass + explicit clinician approval"| approved[("Approved target revision")]
    approved --> checker["INDEPENDENT CONSTRAINT CHECKER<br/>Decimal totals · ranges / minima / ceilings<br/>Actual daily percent-energy · restrictions"]
    draft["Generated plan or single-item substitution draft"] --> checker
    checker --> verdict{"Valid and current?"}
    verdict -->|"No"| unmet["Unmet / stale draft<br/>Approval blocked"]
    verdict -->|"Yes"| planreview["CLINICIAN PLAN APPROVAL<br/>Recheck in the approval transaction"]
    planreview --> plan[("Approved plan revision")]
    changes["Patient, relevant evidence, target or food changes"] -.-> reassess["Reassessment / needs_review<br/>Preserve history; require fresh review"]
    reassess -.-> approved
    reassess -.-> plan
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    classDef human fill:#fff7ed,stroke:#c2410c,color:#431407;
    class evaluate,checker,gate technique;
    class clinician,correct,planreview human;
```

Unknown is not false. A definite exclusion can decide a rule without requesting
unrelated missing facts. Optional guidance stays outside numerical constraints;
`intake` is a soft goal, while ranges, minima, and ceilings are mandatory.
See [patient contracts](PATIENTS.md) and [planning checks](PLANNING.md).

### Resource optimization

**Technique: deterministic heuristic beam search**, implemented as
`beam-source-portions-v5`. It searches food/portion combinations for nutrient fit,
preference match, and variety; it does not optimize monetary cost or inventory.

```mermaid
flowchart TB
    request["Plan request<br/>1–7 days · meal slots · 1–5 items per slot"]
    targets[("Current approved targets<br/>Patient facts and restrictions")]
    pool[("Latest food catalogue revisions<br/>Optional selected pool / exclusions")]
    request --> preflight["Preflight: current targets, energy range,<br/>supported constraints and known restrictions"]
    targets --> preflight
    preflight --> eligible["Eligibility filtering<br/>Allergens · vegetarian suitability<br/>Required nutrients · usable source portions"]
    pool --> eligible
    eligible --> choices["Portion choices: 0.5 / 1 / 1.5 scale<br/>Catalogue shortlist: at most 500 per slot"]
    choices --> objective["Run three weighted objectives<br/>Nutrient fit · preference match · variety"]
    objective --> start["Start each day with an empty beam"]
    start --> expand["BEAM SEARCH: expand next item position<br/>No duplicate food within the same meal"]
    expand --> score["HEURISTIC SCORING<br/>Constraint violation penalty + nutrient fit<br/>+ dislikes + repeated-food penalty"]
    score --> retain["Retain best 32 partial-day candidates<br/>Deterministic ordering"]
    retain --> more{"More item positions?"}
    more -->|"Yes"| expand
    more -->|"No"| daycheck["Independent daily constraint check<br/>Prefer passing candidate; otherwise retain unmet result"]
    daycheck --> days{"More days?"}
    days -->|"Yes: carry used-food history"| start
    days -->|"No"| finalcheck["INDEPENDENT WHOLE-PLAN CHECK<br/>Decimal totals · schedule · portions · restrictions<br/>Daily mandatory nutrient bounds"]
    finalcheck --> drafts["Store alternatives and check reports<br/>Passing drafts or explicit search_failed"]
    drafts --> approval["CLINICIAN REVIEW AND APPROVAL<br/>Only a valid, current alternative can be selected"]
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    classDef human fill:#fff7ed,stroke:#c2410c,color:#431407;
    class expand,score,retain,finalcheck technique;
    class approval human;
```

Eligibility failures return blockers before search. Oversized explicit custom pools
must be narrowed; automatic shortlisting applies to catalogue mode. Partial-day
scoring is a heuristic, not the final verdict. Search is bounded: failure does not
prove infeasibility, optimality is not guaranteed, and alternatives may coincide.
See [search and approval contracts](PLANNING.md#generation-and-approval).

### Knowledge discovery and mining

**Techniques: K-means clustering and content-based nearest-neighbour retrieval.**
Features describe food composition, not patient behaviour. Direct nearest-neighbour
retrieval is the default; cluster-restricted retrieval is an optional method.

```mermaid
flowchart TB
    source["Selected dish in a current approved plan<br/>Exact day / slot / item and pinned food revision"]
    foods[("Candidate food catalogue<br/>Optional selected pool / exclusions")]
    source --> features["CONTENT FEATURES<br/>Protein, carbohydrate and fat per 100 kcal<br/>Fixed reference scaling · Euclidean distance"]
    foods --> features
    features --> kmeans["K-MEANS: macro-energy-kmeans-v1<br/>Deterministic farthest-first seeds<br/>Lloyd assignment / centroid updates, at most 30 iterations"]
    features --> nearest["CONTENT-BASED NEAREST NEIGHBOURS<br/>Default: all feature-complete candidates"]
    kmeans --> clustered["Optional cluster retrieval<br/>Candidates in the source food's cluster"]
    source --> category["Same-category baseline<br/>Exact category match"]
    foods --> category
    nearest --> eligible["Exclude original food; check restrictions,<br/>required nutrients and source portions<br/>Bound catalogue portion choices to 500"]
    clustered --> eligible
    category --> eligible
    eligible --> swap["Try each portion / scale<br/>Replace exactly the selected item in a copy"]
    swap --> check["INDEPENDENT WHOLE-PLAN CONSTRAINT CHECK<br/>Reject replacements violating any mandatory bound"]
    check --> rank["Rank passing replacements<br/>Daily target deviation + dislike penalty<br/>+ nutrient distance for nutrient-based methods"]
    rank --> suggestions["Best passing portion per food<br/>Top suggestions with scores and nutrient differences"]
    suggestions --> select["PATIENT SELECTS REPLACEMENT<br/>Create a separate, freshly checked substitution draft"]
    select --> approve["CLINICIAN APPROVAL<br/>Approved replacement supersedes parent plan"]
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    classDef human fill:#fff7ed,stroke:#c2410c,color:#431407;
    class features,kmeans,nearest,check,rank technique;
    class select,approve human;
```

Similarity requires positive energy and complete macronutrient features. Clustering
does not infer allergens or establish clinical suitability. The implementation fits
the model for the request and returns its metadata, but only the cluster method uses
memberships to restrict retrieval. The existing pilot did not show improved
similarity from clustering. See [mining methods and pilot](MINING.md).

### Cognitive techniques: guideline extraction

**Technique: LLM-assisted structured knowledge extraction**, followed by local
validation and reviewer-controlled publication.

```mermaid
flowchart TB
    document["Clinical guideline URL / PDF / text"]
    document --> snapshot[("Immutable source snapshot<br/>Original bytes where acquired · text · passages · hash")]
    snapshot --> prompt["EXTRACTION PROMPT<br/>Source passages + typed rule schema<br/>Applicability · exceptions · action · citation"]
    prompt -.-> model["HOSTED LLM<br/>Structured guideline extraction"]
    model -.-> validation["LOCAL VALIDATION<br/>JSON Schema / Pydantic · typed predicates<br/>Source quotation and domain checks"]
    validation --> outcome{"Valid structured output?"}
    outcome -->|"No"| failed[("Retained failed extraction run<br/>Validation errors and provenance")]
    outcome -->|"Yes"| drafts[("Review-blocked rule drafts<br/>Immutable revisions and source references")]
    drafts --> review["EVIDENCE REVIEWER<br/>Check clinical meaning, population and source context<br/>Correct drafts and resolve blockers"]
    review --> approve["EXPLICIT RULE APPROVAL<br/>Exact rule revision"]
    approve --> conflict["Publication checks<br/>Population overlap · numeric conflicts<br/>Reviewed catalogue generation"]
    conflict -->|"Unresolved"| review
    conflict -->|"Pass + explicit publication"| published[("Published rule catalogue")]
    published --> engine["Knowledge-based patient rule engine"]
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    classDef human fill:#fff7ed,stroke:#c2410c,color:#431407;
    class prompt,model,validation,conflict technique;
    class review,approve human;
```

The model produces drafts, not approved knowledge. Quotation validation establishes
text integrity, while reviewers assess interpretation. Approval and publication
are distinct operations. See [evidence lifecycle](EVIDENCE.md) and
[hosted inference](INFERENCE.md).

### Cognitive techniques: patient chat

**Technique: evidence-grounded LLM generation with lexical retrieval**
(retrieval-augmented generation), source-ID validation, and revision-bound context.

```mermaid
flowchart TB
    question["Patient question<br/>Optional selected plan / intake date / substitution item"]
    question --> context["Validate current approved patient context<br/>Pin patient, target and evidence revisions"]
    targets[("Approved targets and patient facts")]
    evidence[("Active published rule quotations")]
    targets --> context
    question --> retrieval["LEXICAL EVIDENCE RETRIEVAL<br/>Up to 8 matching published quotations"]
    evidence --> retrieval
    context --> attachments["Deterministic workflow services<br/>Checked plan totals · reported-intake comparisons<br/>Nearest-neighbour substitution suggestions + whole-plan check"]
    retrieval --> prompt["GROUNDED PROMPT ASSEMBLY<br/>Approved context + retrieved evidence + attachments<br/>Up to 3 exchanges from the same snapshot"]
    context --> prompt
    attachments --> prompt
    prompt --> pending[("Commit pending request and context snapshot")]
    pending -.-> llm["HOSTED LLM<br/>Explain approved care with source IDs<br/>Abstain / refer when evidence or authority is insufficient"]
    llm -.-> validate["LOCAL OUTPUT VALIDATION<br/>Schema + source-ID resolution<br/>Attach original quotations in code"]
    validate --> freshness{"Output valid and context<br/>still current after inference?"}
    freshness -->|"No, or output invalid"| failure[("Retained failed run<br/>No current answer returned")]
    freshness -->|"Yes"| answer[("Persist answer, citations and audit<br/>Historical context remains identifiable")]
    answer --> display["Patient sees cited explanation<br/>Replacement action uses the separate draft / approval workflow"]
    classDef technique fill:#ede9fe,stroke:#6d28d9,color:#211044;
    class retrieval,prompt,llm,validate,attachments technique;
```

Chat explains existing records; deterministic services calculate nutrient totals
and check substitutions. An answer cannot change targets or approve a plan.
Source-ID validation verifies source identity, not semantic support for every
generated claim. See [patient conversation contracts](INFERENCE.md#patient-conversation).

### Technique-to-code map

| Technique | Primary implementation |
| --- | --- |
| Knowledge-based rules and three-valued predicates | `patients/engine.py`, `patients/conditions.py` |
| Target approval and reassessment | `patients/service.py`, `nutrition.py` |
| Independent constraint checking and plan approval | `planning/checker.py`, `planning/service.py` |
| Heuristic beam search | `planning/search.py` |
| K-means and content-based retrieval | `foods/clustering.py`, `planning/recommendations.py` |
| LLM guideline extraction and publication | `evidence/extraction.py`, `evidence/service.py`, `evidence/conflicts.py` |
| Evidence-grounded patient chat | `chat.py`, `answers.py`, `chat_workflows.py`, `inference.py` |

Paths above are relative to `src/careloop/`. All six diagrams were successfully
rendered with Mermaid CLI on 2026-10-25. To reproduce with a configured Chromium:

```sh
mmdc -i docs/ARCHITECTURE.md -o /tmp/opencode/careloop-architecture.svg
```

The CLI extracts the Mermaid fences and creates six numbered SVGs. This environment
used `-p /tmp/opencode/careloop-mermaid-puppeteer.json -j 2` to select the installed
`/usr/bin/chromium` with `--no-sandbox`. No live inference or database changes are
needed to render these views.

## Implemented layout

```text
src/careloop/
  api.py                  HTTP routes and application lifetime
  db.py                   Transactional migrations called by API startup
  workflow.py             Shared audit and demo-role transaction helpers
  ingestion.py            Public downloads and external artifact manifests
  inference.py            Shared configured OpenAI-compatible provider client
  answers.py              Cited-education prompts, schema validation, source-ID resolution
  chat.py                 Approved patient context, retrieval and persisted conversation turns
  chat_workflows.py       Plan/intake/substitution attachments and revision stamps
  evaluation/             Frozen experiments, independent audits and offline reports
  migrations/             Ordered, checksum-verified SQL migrations
  evidence/
    models.py             Input contracts and structural validation
    service.py            Transactional source/review/publication operations
    acquisition.py        Approved-domain HTTPS downloads and discovery
    documents.py          Bounded document parsing and passages
    conflicts.py          Structured population/numeric conflict checks
    extraction.py         Hosted extraction runs and review-blocked drafts
  patients/               Facts, CSV import, applicability, target review, routes
  adapters/               Source format → domain model translation (no side effects)
  foods/                  Versioned nutrients, portions, reviewer annotations
  planning/               Bounded search, independent checking, approvals/substitutions
  logging/                Intake revisions, completeness, and target comparisons
  evaluate_foods.py        Reproducible public-food retrieval pilot
tests/                    Workflow and PostgreSQL integration tests
ui/
  src/App.tsx             Application shell, routing and demo session
  src/api.ts              Single typed API client and contracts
  src/state.ts            Shared session and asynchronous request state
  src/navigation.ts       Shared role-specific browser route and menu definitions
  src/screens/            Patient/reviewer/clinician workflows, extraction and cited chat
  src/components/         Shared headers and form/display controls
```

Food clustering lives in `foods/clustering.py`. Share database access and audit conventions;
avoid separate services, generic repositories, a second knowledge database, or
mirroring every HTTP resource into multiple abstraction layers.

## Evidence persistence and consistency

- Sources are immutable text snapshots with title, edition, locator, timestamp,
  and SHA-256. URL/PDF imports also retain original bytes, parser metadata, and
  passages. New editions are new snapshots; URL acquisition is restricted to
  approved domains. See [evidence](EVIDENCE.md) for acquisition limits.
- Rules have immutable revisions. A revision records applicability, exceptions,
  recommendation type, amount/unit where appropriate, source quote/location, and
  unresolved blockers. Quoted text must occur verbatim in the submitted snapshot.
  This checks quotation integrity, not the scientific truth of the interpretation.
- Approval references the exact revision. An edit creates an unapproved revision
  and leaves the earlier published revision available. Self-approval is allowed.
- Approval/publication accept one or multiple explicit rule/revision references.
  Send a source's selected rule IDs for source-level or partial-source review.
  Each submitted selection is atomic; split a selection to review only its valid
  members. Duplicate selections and stale revisions are rejected.
- Publication records a permanent membership list and changes active pointers in
  the same transaction. Publication is distinct from approval. Retirement retains
  the historical active pointer and marks the rule ineligible for future use.
- Publication checks structured population overlap and same-unit numeric conflicts
  against selected and retained active rules. Broader clinical interpretation
  remains manual: reviewers resolve blockers through audited revisions and provide
  a conflict-review note. See [conflict analysis](EVIDENCE.md#structured-conflict-analysis).
- A database-held catalogue lock serializes evidence writes. Publication includes
  the catalogue generation reviewed; any intervening write invalidates it. This
  conservative mechanism fits the small local reviewer workflow. Concurrent edits
  use expected revisions and cannot silently overwrite each other.
- Mutations and audit events commit together. Source and rule history is exposed
  for inspection; no deletion or history-rewrite API is supplied. Database owners
  can still modify storage: this is an application audit trail, not tamper-proof
  infrastructure.

## Contract boundary

Routes use `/api/`. FastAPI generates the current contract at `/openapi.json` and
interactive documentation at `/docs`.

Each write carries `actor: {name, role}` and `reason`. Reviewer actions require the
reviewer label. These labels implement demo workflow guards, not authentication.
Reads are available across the local demo. Keep the deployment loopback-bound.
Patient requests cover generation, substitutions, logging, and chat; clinician
writes cover patient facts, targets and plan approval. Browser routes use explicit
`/patient/`, `/clinician/`, and `/reviewer/` prefixes and descriptive hyphenated names.
Disallowed browser routes redirect to the selected role's home without mounting
the other role's workspace. Clinician intake review is read-only.

`GET /api/evidence/catalogue` returns one consistent snapshot of the generation,
drafts, approval labels, published bodies, and retirement state. Consumers must
exclude retired rules and must not mistake a draft for its published body.
`GET /api/evidence/rules/{id}` includes all revisions. Publications and audit
events have separate read endpoints.

Applicability evaluation now supports a bounded, typed fact vocabulary and
three-valued missing-fact semantics. See [patient contracts](PATIENTS.md) for
supported units, explicit per-kg arithmetic, clinician completion, and limits.

## Workflow integration

Patient target approvals bind immutable patient facts and published rule revisions.
Evidence publication/retirement re-evaluates patient snapshots and flags affected
targets in the same transaction, including newly relevant evidence. Patient edits
flag their target sets. The shared catalogue lock serializes these writes with
approval; patient audit events do not increment the evidence catalogue generation.
Planning consumes only approved, current targets and adds food/restriction checks.
Target readiness alone is not sufficient for planning. Food and target changes
flag affected plans transactionally, while their pinned snapshots remain readable.

Acquired sources and hosted extraction feed the structured draft contract and
share its review boundary. Model experiments live in `notebooks/`; data-source pilots remain separate,
measurable work; neither clinical rules nor generated patient cohorts are seeded.
The NHANES adapter translates explicitly selected public demographic records; no
diagnoses, target approvals, or clinical histories are inferred. SG FoodID and
FNDDS adapters translate food records. Acquisition and output artifacts belong to
`ingestion.py`, including transaction-scoped import functions with explicit actors/reasons.
Adapters only read source formats and construct domain models. See
[foods](FOODS.md) and [planning](PLANNING.md) for unit and lifecycle contracts.
