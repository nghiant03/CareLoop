# SCHEMA DECISION — Knowledge-base backend

**Decision gate:** `PLAN.md` §1 ("Neo4j … Fallback: SQLite + NetworkX if infra time is
squeezed. Decision gate at end of Week 1.") and §4 Week 1 (Lane A: "Decision gate:
Neo4j vs SQLite+NetworkX").

**Date:** 2026-10-08 · **Owner:** Lane A (Knowledge & Rules) · **Status:** DECIDED

---

## Decision

**Adopt SQLite + NetworkX for the prototype.** Neo4j remains the documented reference
design and the target for any post-sprint productionisation, but it is *not* required to
deliver the Week 1–4 exit criteria.

## Rationale

| Criterion | SQLite + NetworkX | Neo4j |
|---|---|---|
| Sprint fit (4 weeks, 4 people) | No server, no Docker, no ops — file in repo | Needs a running instance + driver + auth config |
| Infra burden | `sqlite3` is stdlib; `networkx` is a single pip install | Neo4j service/container, ports, credentials, backups |
| Scale needed | ≪ 5,000 nodes (≈50 rules, ~300 dishes, 20–30 patients, labs, constraints) | Over-provisioned for this dataset |
| Versioning model | Append-only rows + `valid_from`/`valid_to` (see `neo4j_schema_design.md` §4) | Native, but no extra capability we need at this size |
| Graph traversal | NetworkX `MultiDiGraph` covers `shortest_path`/`descendants`/conflict edges | Cypher variable-length paths — nicer, not necessary |
| CI / teammate onboarding | `pytest` runs with zero services | Requires a Neo4j service in CI |
| Migration risk | Low: `nodes`/`edges` tables replay directly into Cypher `MERGE` | — |
| Risk to exit criteria | None | Infra delay could block the Week 2 "graph read/write layer" |

The versioning and provenance requirements (`PLAN.md` §2.1) are satisfiable with the
append-only SQLite schema; no requirement in the plan needs Cypher specifically.

## Consequences

* `rules/neo4j_schema_design.md` is the **single logical model**; both backends implement it.
* The graph layer is accessed through a thin repository interface
  (`load_current_graph`, `append_version`, `point_in_time`) so swapping to Neo4j later
  touches only that module.
* `networkx` is added to the dependency set (pure-Python, no native build). `neo4j` driver
  is **not** a prototype dependency.
* If the team later finds a need for Cypher-only features, the migration path is a
  row-by-row `MERGE` replay of the `nodes`/`edges` tables — the DSL, rules and envelopes
  do not change.

## Revisit trigger

Re-open this decision only if one of the following becomes true:
1. the KB exceeds ~50,000 nodes or traversal latency becomes a bottleneck;
2. a teammate requires live multi-writer graph updates;
3. the evaluation explicitly demands Cypher-queryable provenance.

Until then: **SQLite + NetworkX is the source of truth for the prototype.**
