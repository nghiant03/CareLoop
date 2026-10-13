"""Versioned knowledge-base graph store (SQLite + NetworkX).

Node content is immutable. New versions close the previous validity interval.
Edges are immutable, pinned to node versions, and inactive when either endpoint
closes. Identical edge writes reuse the existing row.

NetworkX views select current state or a timestamp. Validity has one time axis,
not separate valid-time and transaction-time histories. See
``rules/neo4j_schema_design.md`` and ``rules/SCHEMA_DECISION.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx

__all__ = ["KBGraph", "load_kb", "unit_for_nutrient"]

_NUTRIENT_UNITS = {
    "energy_kcal": "kcal",
    "protein_g": "g",
    "sodium_mg": "mg",
    "potassium_mg": "mg",
    "phosphorus_mg": "mg",
    "carbs_g": "g",
    "fat_g": "g",
    "sat_fat_g": "g",
    "fiber_g": "g",
    "sugar_g": "g",
}

_DISH_DATASET_GUIDELINE = "guideline:careloop_dish_dataset"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug or "x"


def unit_for_nutrient(nutrient: str) -> str:
    """Canonical unit for a nutrient field name (e.g. ``sodium_mg`` -> ``mg``)."""
    return _NUTRIENT_UNITS.get(nutrient, "")


def _checksum(props: dict[str, Any]) -> str:
    canonical = json.dumps(props, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def guideline_logical_id(name: str) -> str:
    return f"guideline:{_slug(name)}"


def section_logical_id(guideline: str, section: str) -> str:
    return f"section:{_slug(guideline)}:{_slug(section)}"


def rule_logical_id(rule_id: str) -> str:
    return f"rule:{rule_id}"


def constraint_logical_id(rule_id: str, nutrient: str, kind: str) -> str:
    return f"constraint:{rule_id}:{nutrient}:{kind}"


def exclusion_logical_id(rule_id: str, kind: str, value: str) -> str:
    return f"exclusion:{rule_id}:{kind}:{value}"


def dish_logical_id(dish_id: str) -> str:
    return f"dish:{dish_id}"


def profile_logical_id(dish_id: str) -> str:
    return f"profile:{dish_id}"


def diagnosis_logical_id(code: str) -> str:
    return f"diagnosis:{code}"


def _validate_rule(rule: dict[str, Any]) -> None:
    """Reject a malformed rule before any neighbourhood write.

    Atomic rule appends depend on whole-input validation: a bad rule must fail
    before the first write, not after a partially committed neighbourhood.
    Action types without graph nodes (e.g. ``assert``) pass through unexamined,
    matching what ``append_rule`` chooses not to model.
    """
    if not isinstance(rule, dict):
        raise TypeError("rule must be an object")
    for field in ("rule_id", "guideline", "section"):
        if not rule.get(field):
            raise ValueError(f"rule missing required field {field!r}")
    conditions = rule.get("conditions", [])
    if not isinstance(conditions, list):
        raise TypeError("rule conditions must be a list")
    for cond in conditions:
        if not isinstance(cond, dict):
            raise TypeError("each rule condition must be an object")
        if (
            cond.get("field") == "diagnoses"
            and cond.get("op") == "in"
            and not isinstance(cond.get("value"), list)
        ):
            raise ValueError("diagnoses-in condition value must be a list")
    actions = rule.get("actions", [])
    if not isinstance(actions, list):
        raise TypeError("rule actions must be a list")
    for action in actions:
        if not isinstance(action, dict):
            raise TypeError("each rule action must be an object")
        if action.get("type") == "set_constraint":
            for field in ("nutrient", "kind", "value"):
                if field not in action:
                    raise ValueError(f"set_constraint action missing {field!r}")
            if isinstance(action["value"], bool) or not isinstance(
                action["value"], (int, float)
            ):
                raise ValueError("set_constraint action value must be numeric")
        elif action.get("type") == "exclude":
            for field in ("kind", "value"):
                if field not in action:
                    raise ValueError(f"exclude action missing {field!r}")


class KBGraph:
    """Append-only, versioned knowledge graph backed by SQLite + NetworkX."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()


    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                logical_id  TEXT    NOT NULL,
                version     INTEGER NOT NULL,
                label       TEXT    NOT NULL,
                props       TEXT    NOT NULL,
                source      TEXT,
                checksum    TEXT    NOT NULL,
                valid_from  TEXT    NOT NULL,
                valid_to    TEXT,
                PRIMARY KEY (logical_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_label_current
                ON nodes(label) WHERE valid_to IS NULL;

            CREATE TABLE IF NOT EXISTS edges (
                edge_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_type    TEXT    NOT NULL,
                src_id      TEXT    NOT NULL,
                src_version INTEGER NOT NULL,
                dst_id      TEXT    NOT NULL,
                dst_version INTEGER NOT NULL,
                props       TEXT    NOT NULL DEFAULT '{}',
                valid_from  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id, rel_type);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id, rel_type);

            -- Append-only invariant: node content columns are immutable. Only
            -- the documented `valid_to` closure write is permitted.
            CREATE TRIGGER IF NOT EXISTS trg_nodes_content_immutable
            BEFORE UPDATE ON nodes
            WHEN OLD.props IS NOT NEW.props
              OR OLD.label IS NOT NEW.label
              OR OLD.logical_id IS NOT NEW.logical_id
              OR OLD.version IS NOT NEW.version
              OR OLD.source IS NOT NEW.source
              OR OLD.checksum IS NOT NEW.checksum
              OR OLD.valid_from IS NOT NEW.valid_from
            BEGIN
              SELECT RAISE(ABORT, 'append-only: node content columns are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_edges_append_only
            BEFORE UPDATE ON edges
            BEGIN
              SELECT RAISE(ABORT, 'append-only: edges are immutable');
            END;
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


    def append_node(
        self,
        label: str,
        logical_id: str,
        props: dict[str, Any],
        source: str | None = None,
        version: int | None = None,
        valid_from: str | None = None,
    ) -> int:
        """Append node content and close its previous interval. Return the version.

        Matching current props reuse the existing version, ignoring metadata
        differences. Otherwise allocate a version or require the supplied one
        to exceed every existing version. ``valid_from`` defaults to UTC now
        and cannot predate the open version. Invalid ordering raises ValueError
        before writing.
        """
        with self._conn:
            return self._append_node(
                label, logical_id, props, source, version, valid_from
            )

    def _append_node(
        self,
        label: str,
        logical_id: str,
        props: dict[str, Any],
        source: str | None,
        version: int | None,
        valid_from: str | None,
    ) -> int:
        """Transaction-free node append; the caller owns the transaction."""
        ts = valid_from or _utcnow()
        props_json = json.dumps(props, sort_keys=True, separators=(",", ":"))
        checksum = _checksum(props)
        cur = self._conn.execute(
            "SELECT version, checksum, valid_from FROM nodes WHERE logical_id = ? "
            "AND valid_to IS NULL ORDER BY version DESC LIMIT 1",
            (logical_id,),
        ).fetchone()
        if cur is not None and cur["checksum"] == checksum:
            return int(cur["version"])
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM nodes WHERE logical_id = ?",
            (logical_id,),
        ).fetchone()
        max_version = int(row["v"])
        new_version = version if version is not None else max_version + 1
        if version is not None and new_version <= max_version:
            raise ValueError(
                f"nonmonotone version {new_version} for node {logical_id!r}: "
                f"latest existing version is {max_version}"
            )
        if cur is not None and ts < cur["valid_from"]:
            raise ValueError(
                f"valid_from {ts} predates the open version of {logical_id!r} "
                f"(valid_from {cur['valid_from']})"
            )
        self._conn.execute(
            "UPDATE nodes SET valid_to = ? "
            "WHERE logical_id = ? AND valid_to IS NULL AND version < ?",
            (ts, logical_id, new_version),
        )
        self._conn.execute(
            """
            INSERT INTO nodes
                (logical_id, version, label, props, source, checksum,
                 valid_from, valid_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (logical_id, new_version, label, props_json, source, checksum, ts),
        )
        return new_version

    def append_edge(
        self,
        rel_type: str,
        src_id: str,
        dst_id: str,
        props: dict[str, Any] | None = None,
        src_version: int | None = None,
        dst_version: int | None = None,
        valid_from: str | None = None,
    ) -> int:
        """Append an edge pinned to explicit node versions; returns edge_id.

        Pure insert — edges are immutable, so no history is ever rewritten.
        Re-asserting an edge identical in type, endpoints, pinned versions, and
        props is idempotent and returns the existing edge_id.
        """
        with self._conn:
            return self._append_edge(
                rel_type, src_id, dst_id, props, src_version, dst_version, valid_from
            )

    def _append_edge(
        self,
        rel_type: str,
        src_id: str,
        dst_id: str,
        props: dict[str, Any] | None = None,
        src_version: int | None = None,
        dst_version: int | None = None,
        valid_from: str | None = None,
    ) -> int:
        """Transaction-free edge append; the caller owns the transaction."""
        src_version = src_version if src_version is not None else self._current_version_of(src_id)
        dst_version = dst_version if dst_version is not None else self._current_version_of(dst_id)
        props_json = json.dumps(props or {}, sort_keys=True, separators=(",", ":"))
        ts = valid_from or _utcnow()
        # Reimports must not duplicate edges or the constraints reached through them.
        existing = self._conn.execute(
            "SELECT edge_id FROM edges WHERE rel_type = ? AND src_id = ? "
            "AND src_version = ? AND dst_id = ? AND dst_version = ? AND props = ?",
            (rel_type, src_id, src_version, dst_id, dst_version, props_json),
        ).fetchone()
        if existing is not None:
            return int(existing["edge_id"])
        cur = self._conn.execute(
            """
            INSERT INTO edges
                (rel_type, src_id, src_version, dst_id, dst_version,
                 props, valid_from)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rel_type, src_id, src_version, dst_id, dst_version, props_json, ts),
        )
        assert cur.lastrowid is not None  # INSERT into an INTEGER PRIMARY KEY table.
        return cur.lastrowid

    def append_rule(
        self,
        rule: dict[str, Any],
        source: str | None = None,
        valid_from: str | None = None,
    ) -> int:
        """Append a rule and its graph neighbourhood in one transaction.

        Validate before writing and roll back all changes on failure. Guideline
        revisions reconnect every current section. Return the rule version.
        """
        _validate_rule(rule)
        ts = valid_from or _utcnow()
        rule_id = str(rule["rule_id"])
        guideline = str(rule["guideline"])
        section = str(rule["section"])
        gid = guideline_logical_id(guideline)
        sid = section_logical_id(guideline, section)
        rid = rule_logical_id(rule_id)

        with self._conn:
            self._append_node(
                "Guideline",
                gid,
                {"name": guideline, "url": rule.get("url")},
                source=source or "rules.json",
                version=None,
                valid_from=ts,
            )
            self._append_node(
                "Section",
                sid,
                {"title": section, "guideline": guideline},
                source=source or f"{guideline} / {section}",
                version=None,
                valid_from=ts,
            )
            # Reconnect unchanged sections to the new guideline version without
            # deleting their historical edges.
            for section_lid in self._current_sections_of(guideline):
                self._append_edge("HAS_SECTION", gid, section_lid, valid_from=ts)

            props = {
                "rule_id": rule_id,
                "priority": rule.get("priority", 0),
                "dsl_version": rule.get("dsl_version"),
                "conditions": rule.get("conditions", []),
                "actions": rule.get("actions", []),
                "notes": rule.get("notes"),
                "guideline": guideline,
                "section": section,
                "url": rule.get("url"),
                "verbatim_quote": rule.get("verbatim_quote"),
            }
            self._append_node(
                "Rule",
                rid,
                props,
                source=source or f"{guideline} / {section}",
                version=None,
                valid_from=ts,
            )
            self._append_edge("CITES", rid, sid, valid_from=ts)

            for cond in rule.get("conditions", []):
                if cond.get("field") == "diagnoses" and cond.get("op") == "in":
                    for code in cond.get("value", []):
                        did = diagnosis_logical_id(code)
                        self._append_node(
                            "Diagnosis",
                            did,
                            {"code": code},
                            source=source or "rules.json",
                            version=None,
                            valid_from=ts,
                        )
                        self._append_edge("APPLIES_TO", rid, did, valid_from=ts)

            for action in rule.get("actions", []):
                if action.get("type") == "set_constraint":
                    nutrient = action["nutrient"]
                    kind = action["kind"]
                    cid = constraint_logical_id(rule_id, nutrient, kind)
                    self._append_node(
                        "NutrientConstraint",
                        cid,
                        {
                            "nutrient": nutrient,
                            "kind": kind,
                            "value": action["value"],
                            "unit": action.get("unit") or unit_for_nutrient(nutrient),
                            "rule_id": rule_id,
                            "guideline": guideline,
                            "section": section,
                        },
                        source=source or f"{guideline} / {section}",
                        version=None,
                        valid_from=ts,
                    )
                    self._append_edge("PRODUCES", rid, cid, valid_from=ts)
                elif action.get("type") == "exclude":
                    ekind = action["kind"]
                    evalue = action["value"]
                    fid = exclusion_logical_id(rule_id, ekind, evalue)
                    self._append_node(
                        "ExclusionFlag",
                        fid,
                        {
                            "kind": ekind,
                            "value": evalue,
                            "reason": action.get("reason", ""),
                            "rule_id": rule_id,
                            "guideline": guideline,
                            "section": section,
                        },
                        source=source or f"{guideline} / {section}",
                        version=None,
                        valid_from=ts,
                    )
                    self._append_edge("PRODUCES", rid, fid, valid_from=ts)
            return self._current_version_of(rid)

    def _current_sections_of(self, guideline: str) -> list[str]:
        """Logical ids of the guideline's currently open Section nodes."""
        prefix = f"section:{_slug(guideline)}:"
        rows = self._conn.execute(
            "SELECT logical_id FROM nodes WHERE label = 'Section' AND valid_to IS NULL"
        ).fetchall()
        return sorted(
            r["logical_id"] for r in rows if r["logical_id"].startswith(prefix)
        )


    def _current_version_of(self, logical_id: str) -> int:
        row = self._conn.execute(
            "SELECT version FROM nodes WHERE logical_id = ? AND valid_to IS NULL "
            "ORDER BY version DESC LIMIT 1",
            (logical_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no current version for node {logical_id!r}")
        return int(row["version"])

    def _node_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["logical_id"],
            "label": row["label"],
            "version": int(row["version"]),
            "props": json.loads(row["props"]),
            "source": row["source"],
            "checksum": row["checksum"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
        }


    def nodes(
        self,
        label: str | None = None,
        version: str | None = None,
    ) -> list[dict[str, Any]]:
        """List active nodes, optionally filtered by label.

        ``version`` is an ISO timestamp, not a numeric node revision. None means
        current state; timestamps select valid_from <= t < valid_to, with an
        open valid_to extending indefinitely. Return nodes by logical ID.
        """
        where, params = [], []
        if label is not None:
            where.append("label = ?")
            params.append(label)
        if version is None:
            where.append("valid_to IS NULL")
        else:
            where.append("valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)")
            params += [version, version]
        sql = "SELECT * FROM nodes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY logical_id"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._node_row(r) for r in rows]

    def edges(self, version: str | None = None) -> list[dict[str, Any]]:
        """List edges by ID whose pinned endpoint versions are active.

        ``version`` is an ISO snapshot timestamp, or None for current state.
        Activity is determined from endpoint intervals; a snapshot additionally
        requires the edge itself to have been created (``valid_from``) no later
        than the snapshot time, so later-created edges never appear in earlier
        snapshots despite append-only history.
        """
        if version is None:
            node_pred: tuple[str, list[str]] = ("{alias}.valid_to IS NULL", [])
            edge_pred = ""
            edge_params: list[str] = []
        else:
            node_pred = (
                "{alias}.valid_from <= ? AND ({alias}.valid_to IS NULL OR {alias}.valid_to > ?)",
                [version, version],
            )
            edge_pred = "WHERE e.valid_from <= ?"
            edge_params = [version]
        pred_template, shared_params = node_pred
        src_pred = pred_template.format(alias="n1")
        dst_pred = pred_template.format(alias="n2")
        sql = f"""
            SELECT e.* FROM edges e
            JOIN nodes n1 ON e.src_id = n1.logical_id
                AND e.src_version = n1.version AND {src_pred}
            JOIN nodes n2 ON e.dst_id = n2.logical_id
                AND e.dst_version = n2.version AND {dst_pred}
            {edge_pred}
            ORDER BY e.edge_id
        """
        rows = self._conn.execute(sql, shared_params + shared_params + edge_params).fetchall()
        return [
            {
                "edge_id": r["edge_id"],
                "rel_type": r["rel_type"],
                "src": r["src_id"],
                "src_version": int(r["src_version"]),
                "dst": r["dst_id"],
                "dst_version": int(r["dst_version"]),
                "props": json.loads(r["props"]),
                "valid_from": r["valid_from"],
            }
            for r in rows
        ]

    def current_version(self) -> str | None:
        """Tag of the current KB state: the newest ``valid_from`` timestamp."""
        row = self._conn.execute(
            "SELECT MAX(valid_from) AS t FROM nodes"
        ).fetchone()
        return row["t"] if row and row["t"] else None

    def get_rule(self, rule_id: str, version: int | None = None) -> dict[str, Any] | None:
        """Current (or requested) version of a rule, with its constraints."""
        rid = rule_logical_id(rule_id)
        if version is not None:
            row = self._conn.execute(
                "SELECT * FROM nodes WHERE logical_id = ? AND version = ?",
                (rid, version),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM nodes WHERE logical_id = ? AND valid_to IS NULL "
                "ORDER BY version DESC LIMIT 1",
                (rid,),
            ).fetchone()
        if row is None:
            return None
        node = self._node_row(row)
        out = dict(node["props"])
        out.update(
            {
                "id": node["id"],
                "version": node["version"],
                "valid_from": node["valid_from"],
                "valid_to": node["valid_to"],
                "source": node["source"],
                "checksum": node["checksum"],
            }
        )
        out["constraints"] = self._produced_constraints(rid, node["version"])
        return out

    def _produced_constraints(self, rule_lid: str, rule_version: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.* FROM edges e
            JOIN nodes c ON e.dst_id = c.logical_id AND e.dst_version = c.version
            WHERE e.rel_type = 'PRODUCES' AND e.src_id = ? AND e.src_version = ?
            ORDER BY c.logical_id
            """,
            (rule_lid, rule_version),
        ).fetchall()
        return [
            {
                "id": r["logical_id"],
                **json.loads(r["props"]),
                "version": int(r["version"]),
            }
            for r in rows
        ]

    def rules_for_nutrient(self, nutrient: str) -> list[dict[str, Any]]:
        """Current rules that PRODUCE a NutrientConstraint for ``nutrient``."""
        rows = self._conn.execute(
            """
            SELECT DISTINCT r.logical_id FROM edges e
            JOIN nodes r ON e.src_id = r.logical_id AND e.src_version = r.version
            JOIN nodes c ON e.dst_id = c.logical_id AND e.dst_version = c.version
            WHERE e.rel_type = 'PRODUCES' AND r.label = 'Rule'
              AND r.valid_to IS NULL AND c.valid_to IS NULL
              AND json_extract(c.props, '$.nutrient') = ?
            ORDER BY json_extract(r.props, '$.priority') DESC, r.logical_id
            """,
            (nutrient,),
        ).fetchall()
        out = []
        for r in rows:
            rule_id = r["logical_id"].split(":", 1)[1]
            rule = self.get_rule(rule_id)
            if rule is not None:
                out.append(rule)
        return out

    def dishes_meeting(self, constraint: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
        """Current dishes whose NutrientProfile satisfies ``constraint``.

        ``constraint`` is ``{"nutrient": ..., "kind": "max"|"min"|"target",
        "value": ...}``. A ``target`` is treated as a soft ceiling (values at or
        under the target qualify, closest first).
        """
        nutrient = constraint["nutrient"]
        kind = constraint["kind"]
        value = float(constraint["value"])
        dishes = []
        for node in self.nodes(label="Dish"):
            dish = dict(node["props"])
            profile = self._profile_of(node["id"])
            if profile is None:
                continue
            v = profile["props"].get(nutrient)
            if v is None:
                continue
            if kind in ("max", "target") and float(v) <= value:
                score = value - float(v)
            elif kind == "min" and float(v) >= value:
                score = float(v) - value
            else:
                continue
            dishes.append(
                {
                    **dish,
                    "profile": profile["props"],
                    "slack": score,
                }
            )
        # Closest to the bound first (smallest slack), tie-break on dish id.
        dishes.sort(key=lambda d: (d["slack"], d["dish_id"]))
        return dishes[:limit]

    def _profile_of(self, dish_lid: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT n.* FROM edges e
            JOIN nodes n ON e.dst_id = n.logical_id AND e.dst_version = n.version
            WHERE e.rel_type = 'HAS_PROFILE' AND e.src_id = ?
              AND n.valid_to IS NULL
            LIMIT 1
            """,
            (dish_lid,),
        ).fetchone()
        return self._node_row(row) if row else None

    def node_history(self, node_id: str) -> list[dict[str, Any]]:
        """All versions of a logical node, oldest first.

        Accepts a fully-qualified logical id (``rule:X``) or a bare id, which is
        searched across labels.
        """
        lid = node_id
        if ":" not in node_id:
            row = self._conn.execute(
                "SELECT logical_id FROM nodes WHERE logical_id LIKE '%:' || ? LIMIT 1",
                (node_id,),
            ).fetchone()
            if row is None:
                return []
            lid = row["logical_id"]
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE logical_id = ? ORDER BY version ASC",
            (lid,),
        ).fetchall()
        return [self._node_row(r) for r in rows]

    def graph(self, version: str | None = None) -> nx.MultiDiGraph:
        """Materialise a NetworkX snapshot (current state or point-in-time)."""
        g = nx.MultiDiGraph()
        for node in self.nodes(version=version):
            g.add_node(node["id"], label=node["label"], version=node["version"], **node["props"])
        for edge in self.edges(version=version):
            g.add_edge(
                edge["src"],
                edge["dst"],
                key=edge["rel_type"],
                rel_type=edge["rel_type"],
                **edge["props"],
            )
        return g

    def stats(self) -> dict[str, Any]:
        """Counts of current nodes by label and active edges by relation type."""
        node_counts: dict[str, int] = {}
        for node in self.nodes():
            node_counts[node["label"]] = node_counts.get(node["label"], 0) + 1
        edge_counts: dict[str, int] = {}
        for edge in self.edges():
            edge_counts[edge["rel_type"]] = edge_counts.get(edge["rel_type"], 0) + 1
        return {
            "db_path": self.db_path,
            "current_version": self.current_version(),
            "node_counts": node_counts,
            "edge_counts": edge_counts,
        }


    def rules(self) -> list[dict[str, Any]]:
        """All current rules."""
        out = []
        for node in self.nodes(label="Rule"):
            rule_id = node["id"].split(":", 1)[1]
            rule = self.get_rule(rule_id)
            if rule is not None:
                out.append(rule)
        out.sort(key=lambda r: (-r.get("priority", 0), r["rule_id"]))
        return out

    def dishes(self) -> list[dict[str, Any]]:
        """All current dishes with their nutrient profile attached."""
        out = []
        for node in self.nodes(label="Dish"):
            dish = dict(node["props"])
            profile = self._profile_of(node["id"])
            dish["profile"] = profile["props"] if profile else None
            out.append(dish)
        out.sort(key=lambda d: d["dish_id"])
        return out


def load_kb(
    rules_path: str | Path,
    dishes_path: str | Path,
    db_path: str | Path = ":memory:",
    valid_from: str | None = None,
    *,
    rules_document: dict | None = None,
    dishes_document: list[dict] | None = None,
    source: str | None = None,
) -> KBGraph:
    """Build a graph from explicit files or an already validated release snapshot.

    Release documents bypass file reads; source identifies the published release
    without replacing the catalogue's original nutrient provenance.
    """
    ts = valid_from or _utcnow()
    kb = KBGraph(db_path)

    if rules_document is None:
        with open(rules_path, "r", encoding="utf-8") as fh:
            rules_doc = json.load(fh)
    else:
        rules_doc = rules_document
    for rule in rules_doc.get("rules", []):
        kb.append_rule(rule, source=source or "rules.json", valid_from=ts)

    kb.append_node(
        "Guideline",
        _DISH_DATASET_GUIDELINE,
        {"name": "CareLoop dish dataset", "url": None},
        source=source or "dishes.json",
        valid_from=ts,
    )

    if dishes_document is None:
        with open(dishes_path, "r", encoding="utf-8") as fh:
            dishes = json.load(fh)
    else:
        dishes = dishes_document
    nutrients = [
        "energy_kcal", "protein_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
        "carbs_g", "fat_g", "sat_fat_g", "fiber_g", "sugar_g",
    ]
    for dish in dishes:
        dish_id = str(dish["dish_id"])
        did = dish_logical_id(dish_id)
        pid = profile_logical_id(dish_id)
        provenance = dish.get("provenance", "unknown")
        kb.append_node(
            "Dish",
            did,
            {
                "dish_id": dish_id,
                "name": dish.get("name"),
                "cuisine": dish.get("cuisine"),
                "category": dish.get("category"),
                "tags": dish.get("tags", []),
                "portion_g": dish.get("portion_g"),
            },
            source=f"{source or 'dishes.json'}#{dish_id}",
            valid_from=ts,
        )
        profile_props = {key: dish.get(key) for key in nutrients}
        profile_props.update(
            {
                "dish_id": dish_id,
                "provenance": provenance,
                "portion_g": dish.get("portion_g"),
            }
        )
        kb.append_node(
            "NutrientProfile",
            pid,
            profile_props,
            source=str(provenance),
            valid_from=ts,
        )
        kb.append_edge("HAS_PROFILE", did, pid, valid_from=ts)
        kb.append_edge(
            "DERIVED_FROM",
            pid,
            _DISH_DATASET_GUIDELINE,
            props={"provenance": provenance},
            valid_from=ts,
        )
    return kb
