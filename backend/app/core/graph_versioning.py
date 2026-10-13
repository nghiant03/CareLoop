"""Standalone versioned-graph prototype, separate from the application's KBGraph.

Nodes and relationships retain JSON payload versions with valid_from/valid_to
intervals. Appending closes the current interval and inserts a new row; NetworkX
materializes current state on demand. This is one time axis, not bitemporal
storage. The default database is ``data/careloop_graph.sqlite3``.

Demo: ``python -m backend.app.core.graph_versioning``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx

__all__ = ["DEFAULT_DB_PATH", "GraphStore"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = Path(
    os.environ.get("CARE_LOOP_GRAPH_DB", _REPO_ROOT / "data" / "careloop_graph.sqlite3")
)

NodeRef = tuple[str, str] | str


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _split_ref(ref: NodeRef) -> tuple[str, str]:
    """Normalise ``(label, id)`` or ``"label:id"`` into a tuple."""
    if isinstance(ref, tuple):
        label, node_id = ref
        return str(label), str(node_id)
    if ":" not in ref:
        raise ValueError(f"node reference {ref!r} must be (label, id) or 'label:id'")
    label, node_id = ref.split(":", 1)
    return label, node_id


class GraphStore:
    """Versioned SQLite graph that appends payload versions and closes intervals."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()


    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_key   TEXT NOT NULL,
                    label      TEXT NOT NULL,
                    node_id    TEXT NOT NULL,
                    version    INTEGER NOT NULL,
                    payload    TEXT NOT NULL DEFAULT '{}',
                    valid_from TEXT NOT NULL,
                    valid_to   TEXT,
                    PRIMARY KEY (node_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_current
                    ON nodes(node_key, valid_to);

                CREATE TABLE IF NOT EXISTS edges (
                    edge_key   TEXT NOT NULL,
                    rel_type   TEXT NOT NULL,
                    src_key    TEXT NOT NULL,
                    dst_key    TEXT NOT NULL,
                    version    INTEGER NOT NULL,
                    payload    TEXT NOT NULL DEFAULT '{}',
                    valid_from TEXT NOT NULL,
                    valid_to   TEXT,
                    PRIMARY KEY (edge_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_edges_current
                    ON edges(edge_key, valid_to);
                """
            )


    def append_node(
        self,
        label: str,
        node_id: str,
        payload: dict[str, Any] | None = None,
        version: int | None = None,
    ) -> int:
        """Append a new version of a node; returns the version number."""
        node_key = f"{label}:{node_id}"
        now = _utcnow()
        payload_json = json.dumps(payload or {}, sort_keys=True)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM nodes WHERE node_key = ?",
                (node_key,),
            ).fetchone()
            new_version = version if version is not None else int(row["v"]) + 1
            conn.execute(
                "UPDATE nodes SET valid_to = ? WHERE node_key = ? AND valid_to IS NULL",
                (now, node_key),
            )
            conn.execute(
                """
                INSERT INTO nodes
                    (node_key, label, node_id, version, payload, valid_from, valid_to)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (node_key, label, node_id, new_version, payload_json, now),
            )
        return new_version

    def append_relationship(
        self,
        rel_type: str,
        src: NodeRef,
        dst: NodeRef,
        payload: dict[str, Any] | None = None,
        version: int | None = None,
    ) -> int:
        """Append a new version of a directed relationship; returns version."""
        src_label, src_id = _split_ref(src)
        dst_label, dst_id = _split_ref(dst)
        src_key = f"{src_label}:{src_id}"
        dst_key = f"{dst_label}:{dst_id}"
        edge_key = f"{rel_type}|{src_key}|{dst_key}"
        now = _utcnow()
        payload_json = json.dumps(payload or {}, sort_keys=True)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM edges WHERE edge_key = ?",
                (edge_key,),
            ).fetchone()
            new_version = version if version is not None else int(row["v"]) + 1
            conn.execute(
                "UPDATE edges SET valid_to = ? WHERE edge_key = ? AND valid_to IS NULL",
                (now, edge_key),
            )
            conn.execute(
                """
                INSERT INTO edges
                    (edge_key, rel_type, src_key, dst_key, version, payload,
                     valid_from, valid_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    edge_key,
                    rel_type,
                    src_key,
                    dst_key,
                    new_version,
                    payload_json,
                    now,
                ),
            )
        return new_version


    def get_current(self, label: str, node_id: str) -> dict[str, Any] | None:
        """Return the current version of a node, or ``None``."""
        node_key = f"{label}:{node_id}"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM nodes
                WHERE node_key = ? AND valid_to IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                (node_key,),
            ).fetchone()
        return self._node_row(row) if row else None

    def history(self, label: str, node_id: str) -> list[dict[str, Any]]:
        """Return every version of a node, oldest first."""
        node_key = f"{label}:{node_id}"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE node_key = ? ORDER BY version ASC",
                (node_key,),
            ).fetchall()
        return [self._node_row(r) for r in rows]

    def current_nodes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE valid_to IS NULL ORDER BY node_key"
            ).fetchall()
        return [self._node_row(r) for r in rows]

    def current_edges(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM edges WHERE valid_to IS NULL ORDER BY edge_key"
            ).fetchall()
        return [self._edge_row(r) for r in rows]

    @staticmethod
    def _node_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "label": row["label"],
            "id": row["node_id"],
            "version": row["version"],
            "payload": json.loads(row["payload"]),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
        }

    @staticmethod
    def _edge_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "rel_type": row["rel_type"],
            "src": row["src_key"],
            "dst": row["dst_key"],
            "version": row["version"],
            "payload": json.loads(row["payload"]),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
        }


    def materialise_current(self) -> nx.MultiDiGraph:
        """Build a NetworkX graph of the current-state subgraph."""
        graph = nx.MultiDiGraph()
        for node in self.current_nodes():
            graph.add_node(
                f"{node['label']}:{node['id']}",
                label=node["label"],
                node_id=node["id"],
                version=node["version"],
                **node["payload"],
            )
        for edge in self.current_edges():
            graph.add_edge(
                edge["src"],
                edge["dst"],
                key=edge["rel_type"],
                rel_type=edge["rel_type"],
                version=edge["version"],
                **edge["payload"],
            )
        return graph

    def close(self) -> None:
        """No-op: connections are short-lived per operation."""


def _demo(db_path: str | Path | None = None) -> None:
    import tempfile

    if db_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".sqlite3", prefix="careloop_demo_")
        os.close(fd)
        db_path = tmp
        print(f"[demo] using temporary DB: {db_path}")

    store = GraphStore(db_path)
    print("\n[demo] append nodes + relationships ...")
    store.append_node("Patient", "p-1", {"name": "Alice Tan", "age": 58, "weight_kg": 72.0})
    store.append_node("Diagnosis", "T2D", {"name": "Type 2 Diabetes"})
    store.append_node("Diagnosis", "CKD_stage_3", {"name": "CKD stage 3"})
    store.append_relationship("HAS_DIAGNOSIS", ("Patient", "p-1"), ("Diagnosis", "T2D"))
    store.append_relationship(
        "HAS_DIAGNOSIS", ("Patient", "p-1"), ("Diagnosis", "CKD_stage_3")
    )
    v2 = store.append_node(
        "Patient", "p-1", {"name": "Alice Tan", "age": 58, "weight_kg": 70.5}
    )
    print(f"[demo] Patient:p-1 updated -> version {v2}")

    print("\n[demo] get_current('Patient', 'p-1'):")
    print(json.dumps(store.get_current("Patient", "p-1"), indent=2))

    print("\n[demo] history('Patient', 'p-1'):")
    for row in store.history("Patient", "p-1"):
        print(
            f"  v{row['version']}  weight={row['payload'].get('weight_kg')}  "
            f"valid_from={row['valid_from']}  valid_to={row['valid_to']}"
        )

    print("\n[demo] materialised current graph (NetworkX):")
    g = store.materialise_current()
    print(f"  nodes={g.number_of_nodes()} edges={g.number_of_edges()}")
    for src, dst, key, data in g.edges(keys=True, data=True):
        print(f"  {src} -[{key}]-> {dst}")

    if db_path and str(db_path).startswith(tempfile.gettempdir()):
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    _demo()
