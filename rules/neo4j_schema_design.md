# CareLoop Knowledge Graph — Schema Design & Versioning

**Owner:** Lane A (Knowledge & Rules) · **Status:** design (Week 1) · **Decision:** see `SCHEMA_DECISION.md` (prototype uses SQLite + NetworkX; this document is the reference model both backends implement).

This is the design for the versioned knowledge base that stores the guideline → rule →
constraint chain described in `PLAN.md` §2.1:

```
Patient → Diagnosis → Guideline → Rule → NutrientConstraint → Dish → NutrientProfile
```

Two backends implement the same logical model:

1. **Neo4j** (primary/reference) — property graph + Cypher, append-only with `valid_from` / `valid_to`.
2. **SQLite + NetworkX** (prototype fallback, chosen for Week 1) — relational tables for versioned
   nodes/edges, materialised into a `networkx.MultiDiGraph` for traversal.

---

## 1. Node labels (Neo4j)

Every versioned node carries the common audit properties:

| Property | Type | Meaning |
|---|---|---|
| `id` | string | Stable logical id, shared by all versions of the entity (e.g. `rule:CKD-2024-SODIUM-2000`) |
| `version` | int | Monotonic version counter for this logical id (1, 2, 3 …) |
| `valid_from` | datetime | When this version became current |
| `valid_to` | datetime \| null | When it was superseded; `null` = current |
| `source` | string | Guideline + section, e.g. `KDIGO 2024 §3.4` |
| `created_by` | string | Author / importer |
| `checksum` | string | Content hash for change detection |

| Label | Key properties | Maps to |
|---|---|---|
| `Patient` | `patient_id`, `age`, `sex`, `weight_kg`, `bmi` | `PatientSummary` |
| `Diagnosis` | `code` (`CKD_stage_4`, `HTN`, `T2D`), `description` | `PatientSummary.diagnoses` |
| `Guideline` | `name`, `year`, `publisher`, `url` | `CitationSource.guideline` |
| `Section` | `number`, `title`, `quote` | `CitationSource.section` / `verbatim_quote` |
| `Rule` | `rule_id`, `priority`, `dsl_version`, `conditions` (JSON), `actions` (JSON), `notes` | `rules.json` entries |
| `NutrientConstraint` | `nutrient`, `kind` (`target`/`min`/`max`), `value`, `unit` | `NutrientConstraint` |
| `ExclusionFlag` | `kind`, `value`, `reason` | `ExclusionFlag` |
| `Dish` | `dish_id`, `name`, `cuisine`, `category`, `healthier_choice` | food store |
| `NutrientProfile` | `energy_kcal`, `protein_g`, `sodium_mg`, `potassium_mg`, `phosphorus_mg`, `carbs_g`, `fat_g`, `sat_fat_g`, `fiber_g`, `sugar_g`, `provenance` | per-dish nutrients |
| `Lab` | `serum_K_meq_L`, `serum_PO4_mg_dL`, `egfr`, `taken_at` | longitudinal labs |
| `Medication` | `name`, `drug_class` (`ACEi`, `ARB`, `SGLT2i`, `metformin`, `loop_diuretic`, `thiazide`) | `PatientSummary.meds` |
| `Envelope` | `envelope_id`, `status`, `version`, `priority_basis`, `proposed_at`, `approved_by` | `NutrientEnvelope` |
| `RuleFire` | `rule_id`, `fired_at`, `patient_summary`, `action_summary`, `priority` | `RuleFire` |

> The `Rule` node stores `conditions` / `actions` as JSON strings so the same DSL from
> `rules/rules.json` round-trips without translation. CLIPS remains the execution engine;
> the graph is the *knowledge store + provenance*, not the matcher.

---

## 2. Relationships (edges)

All edges are also versioned (`valid_from`, `valid_to`) and carry `source` where meaningful.

```
(:Patient)-[:HAS_DIAGNOSIS {valid_from, valid_to}]->(:Diagnosis)
(:Patient)-[:HAS_LAB {taken_at}]->(:Lab)
(:Patient)-[:TAKES {valid_from, valid_to}]->(:Medication)
(:Patient)-[:HAS_ENVELOPE]->(:Envelope)
(:Diagnosis)-[:GOVERNED_BY]->(:Guideline)
(:Guideline)-[:HAS_SECTION]->(:Section)
(:Rule)-[:CITES]->(:Section)
(:Rule)-[:APPLIES_TO]->(:Diagnosis)
(:Rule)-[:PRODUCES]->(:NutrientConstraint)
(:Rule)-[:PRODUCES]->(:ExclusionFlag)
(:Rule)-[:FIRED_IN {fired_at}]->(:RuleFire)
(:RuleFire)-[:FOR_ENVELOPE]->(:Envelope)
(:Envelope)-[:HAS_CONSTRAINT]->(:NutrientConstraint)
(:Envelope)-[:HAS_EXCLUSION]->(:ExclusionFlag)
(:NutrientConstraint)-[:CONSTRAINS]->(:Dish)
(:Dish)-[:HAS_PROFILE]->(:NutrientProfile)
(:NutrientProfile)-[:DERIVED_FROM {provenance}]->(:Guideline)
(:NutrientConstraint)-[:SUPERSEDES]->(:NutrientConstraint)   ; conflict resolution audit
```

### Conflict-resolution edges
When two rules propose a value for the same `(nutrient, kind)`, the engine records:

```
(:NutrientConstraint {rule_id:"DASH-2025-SODIUM-2300"})-[:LOSES_TO {reason:"CKD p90 > DASH p70"}]->(:NutrientConstraint {rule_id:"CKD-2024-SODIUM-2000"})
```

This makes `priority_basis` ("CKD > HTN > T2D on sodium") queryable and auditable.

---

## 3. Versioning strategy

**Append-only, bi-temporal-lite.** We never mutate or delete a versioned node/edge.

* A change to a rule creates a **new node with the same `id`** and `version + 1`.
* The previous version's `valid_to` is set to the new `valid_from` (one write, no deletion).
* A "current" query filters on `valid_to IS NULL` (or `valid_from <= t AND (valid_to IS NULL OR valid_to > t)` for point-in-time reads).
* `RuleFire` and `Envelope` are themselves immutable event records; they pin the *version ids*
  they consumed, so an envelope can always be re-explained exactly as it was approved.

Example Cypher — current rule set:

```cypher
MATCH (r:Rule) WHERE r.valid_to IS NULL
RETURN r.rule_id, r.priority, r.conditions, r.actions
ORDER BY r.priority DESC;
```

Point-in-time reconstruction (what did the KB look like on 2026-10-01?):

```cypher
MATCH (r:Rule)
WHERE r.valid_from <= datetime('2026-10-01T00:00:00Z')
  AND (r.valid_to IS NULL OR r.valid_to > datetime('2026-10-01T00:00:00Z'))
RETURN r.rule_id, r.version;
```

Uniqueness constraint (Neo4j):

```cypher
CREATE CONSTRAINT rule_version_unique IF NOT EXISTS
FOR (r:Rule) REQUIRE (r.id, r.version) IS UNIQUE;
CREATE INDEX rule_current IF NOT EXISTS FOR (r:Rule) ON (r.valid_to);
```

---

## 4. Alternative backend — SQLite + NetworkX (prototype)

The chosen prototype backend (see `SCHEMA_DECISION.md`). It stores the same logical model
relationally and builds an in-memory `networkx.MultiDiGraph` for traversal.

### 4.1 SQLite tables

```sql
-- Versioned nodes: one row per version, PK (logical_id, version)
CREATE TABLE nodes (
    logical_id  TEXT    NOT NULL,      -- e.g. 'rule:CKD-2024-SODIUM-2000'
    version     INTEGER NOT NULL,
    label       TEXT    NOT NULL,      -- 'Rule' | 'Dish' | 'NutrientConstraint' ...
    props       TEXT    NOT NULL,      -- JSON blob
    valid_from  TEXT    NOT NULL,      -- ISO-8601 UTC
    valid_to    TEXT,                  -- NULL = current
    source      TEXT,
    checksum    TEXT,
    PRIMARY KEY (logical_id, version)
);
CREATE INDEX idx_nodes_current ON nodes(label) WHERE valid_to IS NULL;

-- Versioned edges
CREATE TABLE edges (
    edge_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id      TEXT NOT NULL,         -- logical_id
    src_version INTEGER NOT NULL,
    dst_id      TEXT NOT NULL,
    dst_version INTEGER NOT NULL,
    rel_type    TEXT NOT NULL,         -- 'CITES' | 'PRODUCES' | 'LOSES_TO' ...
    props       TEXT,                  -- JSON
    valid_from  TEXT NOT NULL,
    valid_to    TEXT
);
CREATE INDEX idx_edges_src ON edges(src_id, valid_to);
CREATE INDEX idx_edges_dst ON edges(dst_id, valid_to);
```

### 4.2 NetworkX materialisation

```python
import json, sqlite3, networkx as nx

def load_current_graph(db_path: str) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    con = sqlite3.connect(db_path)
    for lid, ver, label, props in con.execute(
        "SELECT logical_id, version, label, props FROM nodes WHERE valid_to IS NULL"
    ):
        g.add_node(lid, label=label, version=ver, **json.loads(props))
    for src, dst, rel, props in con.execute(
        "SELECT src_id, dst_id, rel_type, props FROM edges WHERE valid_to IS NULL"
    ):
        g.add_edge(src, dst, key=rel, **(json.loads(props) if props else {}))
    return g
```

### 4.3 Mapping table — Neo4j ⇄ SQLite

| Neo4j | SQLite + NetworkX |
|---|---|
| Node label + properties | `nodes.label` + `nodes.props` JSON |
| `(a)-[:REL]->(b)` | `edges(src_id, rel_type, dst_id)` |
| `WHERE valid_to IS NULL` | same predicate in SQL / on the loaded graph |
| `MERGE` on `(id, version)` | `INSERT OR IGNORE` on PK `(logical_id, version)` |
| Cypher variable-length path | `networkx.shortest_path` / `nx.descendants` |
| `LOSES_TO` conflict edge | `edges.rel_type = 'LOSES_TO'` |
| Constraint / index | `PRIMARY KEY` + `CREATE INDEX` |

### 4.4 Why this is sufficient for ≤5,000 nodes
A 4-week prototype KB is small: ~50 rules × ~2 versions + ~300 dishes + 20–30 patients +
labs/constraints ≈ well under 5,000 nodes. NetworkX loads that in milliseconds; SQLite
gives ACID versioning with zero infrastructure. Migration to Neo4j later is a row-by-row
replay of `nodes` / `edges` into `MERGE` statements — the logical model is unchanged.

---

## 5. Provenance / audit requirements

1. Every `NutrientConstraint` and `ExclusionFlag` in an approved envelope traces to a `Rule`
   via `PRODUCES`, and to a `Section` via `Rule-[:CITES]->Section`.
2. Every `Dish` nutrient value carries `NutrientProfile.provenance`
   (`HPB_SG_FoodID` | `USDA_FDC` | `estimated`) — required because HPB dish data often lacks K/P
   (`PLAN.md` §6).
3. Envelopes are immutable once `APPROVED`; edits create a new `Envelope` version and a new
   `RuleFire` set. Nothing is overwritten.
