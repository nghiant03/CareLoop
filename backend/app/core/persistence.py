"""Durable application store for CareLoop (Milestone 3 persistence foundation).

Single SQLite database (stdlib ``sqlite3`` only) holding everything that
previously lived in process-local dicts:

* ``plans``            — generated meal plans (POST /plans output documents)
* ``meal_logs``        — adherence logs, one dish per (patient, date, meal)
* ``envelope_journal`` — append-only lifecycle history of nutrient envelopes
* ``observations``     — longitudinal clinical observations (labs, eGFR, ...)
* ``simulations``      — clinician what-if simulations
* ``review_items``     — clinician review queue (alerts -> acknowledgement ->
                         recorded action)

Connection policy
-----------------
Unlike ``backend.app.kb.graph_store.KBGraph`` (one long-lived connection per
instance, ``check_same_thread=False``), this module opens a **short-lived
connection per call** — the pattern already used by
``backend.app.core.graph_versioning.GraphStore``. Rationale:

* every read goes straight to disk, so "survives restart" is trivially true
  and demonstrable (no cached in-memory state);
* no connection is shared across threads, so ``check_same_thread`` is moot;
* the prototype's write volume is tiny, so per-call connect cost is negligible.

The database path is resolved **lazily, at call time**, from the
``CARELOOP_APP_DB`` environment variable (default
``<repo>/data/careloop_app.sqlite3``). Lazy resolution is deliberate: pytest
conftest files set the env var before the first store call without needing to
import-order gymnastics.

Identifier minting mirrors the existing sequential patterns (envelope ids
``ENV-<pid>-001``, plan ids ``PLAN-<pid>-001``): ids are
``<PREFIX>-<patient_id>-<NNN>``, minted under the module lock by scanning the
existing rows for the highest suffix and incrementing. Ids are never reused
because rows are never deleted from the keyed tables (except meal logs, which
are keyed by a natural id and have no minted id).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date as date_type, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from backend.app.models.envelope import NutrientEnvelope

__all__ = [
    "db_path",
    "init_db",
    "clear_all",
    # plans
    "save_plan",
    "get_plan",
    "list_plans",
    "latest_plan_for_patient",
    # meal logs
    "put_log",
    "get_log",
    "list_logs",
    "delete_logs_for_patient",
    "count_logs",
    "clear_logs",
    # envelope journal
    "journal_envelope",
    "envelope_effective_at",
    "list_envelope_history",
    # observations
    "add_observation",
    "list_observations",
    # simulations
    "save_simulation",
    "list_simulations",
    # review queue
    "create_review_item",
    "list_review_items",
    "acknowledge_review_item",
    "record_review_action",
    "get_review_item",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB = _REPO_ROOT / "data" / "careloop_app.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    patient_id TEXT PRIMARY KEY,
    document_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    plan_id          TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL,
    envelope_id      TEXT NOT NULL,
    envelope_version INTEGER NOT NULL,
    engine           TEXT,
    feasible         INTEGER NOT NULL,
    violation_count  INTEGER NOT NULL DEFAULT 0,
    objectives_json  TEXT,
    days_json        TEXT,
    adequacy_json    TEXT,
    kb_version       TEXT,
    document_json    TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_patient ON plans(patient_id, created_at);

CREATE TABLE IF NOT EXISTS meal_logs (
    patient_id TEXT NOT NULL,
    date       TEXT NOT NULL,
    meal       TEXT NOT NULL,
    dish_id    TEXT NOT NULL,
    logged_at  TEXT NOT NULL,
    PRIMARY KEY (patient_id, date, meal)
);
CREATE INDEX IF NOT EXISTS idx_meal_logs_patient_date
    ON meal_logs(patient_id, date);

CREATE TABLE IF NOT EXISTS envelope_journal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event         TEXT,
    envelope_id   TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    version       INTEGER NOT NULL,
    status        TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    effective_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_patient_effective
    ON envelope_journal(patient_id, effective_at);
CREATE INDEX IF NOT EXISTS idx_journal_envelope
    ON envelope_journal(envelope_id);

CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL,
    metric         TEXT NOT NULL,
    value          REAL NOT NULL,
    unit           TEXT,
    source         TEXT,
    observed_at    TEXT NOT NULL,
    recorded_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_patient
    ON observations(patient_id, observed_at);

CREATE TABLE IF NOT EXISTS simulations (
    simulation_id        TEXT PRIMARY KEY,
    patient_id           TEXT NOT NULL,
    base_envelope_id     TEXT NOT NULL,
    proposed_targets_json TEXT NOT NULL,
    comparison_json      TEXT,
    status               TEXT NOT NULL DEFAULT 'OPEN',
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simulations_patient
    ON simulations(patient_id, created_at);

CREATE TABLE IF NOT EXISTS review_items (
    review_id          TEXT PRIMARY KEY,
    patient_id         TEXT NOT NULL,
    source             TEXT NOT NULL,
    payload_json       TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'OPEN',
    created_at         TEXT NOT NULL,
    acknowledged_at    TEXT,
    action_json        TEXT,
    linked_envelope_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status, created_at);
CREATE INDEX IF NOT EXISTS idx_review_patient ON review_items(patient_id);
"""

# Serialises mint-and-insert sequences so concurrent callers cannot mint the
# same sequential id. SQLite's own write locking covers the actual writes; this
# lock keeps the read-max-then-insert idiom atomic within the process.
_LOCK = Lock()

# Schema is applied once per resolved path (paths are resolved lazily, so a
# test that repoints CARELOOP_APP_DB gets a fresh initialisation).
_INIT_LOCK = Lock()
_INITIALIZED: set[str] = set()

_MEAL_ORDER = ("breakfast", "lunch", "dinner")


def db_path() -> str:
    """Resolve the app database path lazily from ``CARELOOP_APP_DB``."""
    return os.environ.get("CARELOOP_APP_DB") or str(_DEFAULT_DB)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date_type.today().isoformat()


def _connect() -> sqlite3.Connection:
    """Open a short-lived connection, applying the schema once per path."""
    path = db_path()
    parent = Path(path).parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    if path not in _INITIALIZED:
        with _INIT_LOCK:
            if path not in _INITIALIZED:  # double-checked
                conn = sqlite3.connect(path)
                try:
                    conn.executescript(_SCHEMA)
                    if "items_json" not in {r[1] for r in conn.execute("PRAGMA table_info(meal_logs)")}:
                        conn.execute("ALTER TABLE meal_logs ADD COLUMN items_json TEXT")
                    conn.commit()
                finally:
                    conn.close()
                _INITIALIZED.add(path)
    conn = sqlite3.connect(path, factory=_Connection)
    conn.row_factory = sqlite3.Row
    return conn


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def init_db() -> None:
    """Idempotently create the schema (and the database file if missing)."""
    conn = _connect()
    conn.close()


def _mint_id(conn: sqlite3.Connection, table: str, prefix: str, column: str) -> str:
    """Next sequential ``<prefix><NNN>`` id for ``table`` (collision-safe).

    Scans the existing ids under ``prefix`` for the highest numeric suffix;
    never reuses an id because rows are never deleted from ``table``.
    """
    # Acquire the write reservation before reading ids, including across workers.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    seq = 0
    like = (
        prefix.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
    )
    rows = conn.execute(
        f"SELECT {column} AS id FROM {table} WHERE {column} LIKE ? ESCAPE '\\'",
        (like,),
    ).fetchall()
    for row in rows:
        suffix = str(row["id"])[len(prefix):]
        if suffix.isdigit():
            seq = max(seq, int(suffix))
    candidate = f"{prefix}{seq + 1:03d}"
    while conn.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ?", (candidate,)
    ).fetchone() is not None:
        seq += 1
        candidate = f"{prefix}{seq + 1:03d}"
    return candidate


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


def save_plan(
    patient_id: str,
    envelope_id: str,
    envelope_version: int,
    engine: Optional[str],
    feasible: bool,
    violation_count: int,
    objectives: Optional[list[dict[str, Any]]] = None,
    days: Optional[list[dict[str, Any]]] = None,
    adequacy: Optional[list[dict[str, Any]]] = None,
    kb_version: Optional[str] = None,
    document: Optional[dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> str:
    """Persist one generated meal plan; returns the minted plan id.

    ``document`` (optional) is the full API response document, stored verbatim
    so ``get_plan`` can reconstruct it byte-for-byte. ``created_at`` defaults
    to the current UTC timestamp.
    """
    created_at = created_at or _utcnow()
    with _LOCK, _connect() as conn:
        plan_id = _mint_id(conn, "plans", f"PLAN-{patient_id}-", "plan_id")
        conn.execute(
            """
            INSERT INTO plans
                (plan_id, patient_id, envelope_id, envelope_version, engine,
                 feasible, violation_count, objectives_json, days_json,
                 adequacy_json, kb_version, document_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                patient_id,
                envelope_id,
                int(envelope_version),
                engine,
                int(bool(feasible)),
                int(violation_count),
                json.dumps(objectives) if objectives is not None else None,
                json.dumps(days) if days is not None else None,
                json.dumps(adequacy) if adequacy is not None else None,
                kb_version,
                json.dumps(document) if document is not None else None,
                created_at,
            ),
        )
    return plan_id


def _plan_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "plan_id": row["plan_id"],
        "patient_id": row["patient_id"],
        "envelope_id": row["envelope_id"],
        "envelope_version": int(row["envelope_version"]),
        "engine": row["engine"],
        "feasible": bool(row["feasible"]),
        "violation_count": int(row["violation_count"]),
        "kb_version": row["kb_version"],
        "created_at": row["created_at"],
    }


def get_plan(plan_id: str) -> Optional[dict[str, Any]]:
    """Full stored plan document (``None`` when the id is unknown).

    The returned mapping is the stored response document plus ``plan_id`` and
    ``saved_at`` (the storage timestamp). When no verbatim document was stored,
    the document is reconstructed from the column fields.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    if row is None:
        return None
    if row["document_json"]:
        document = json.loads(row["document_json"])
    else:
        document = {
            "patient_id": row["patient_id"],
            "envelope_id": row["envelope_id"],
            "feasible": bool(row["feasible"]),
            "engine": row["engine"],
            "violation_count": int(row["violation_count"]),
            "objectives": json.loads(row["objectives_json"]) if row["objectives_json"] else None,
            "days": json.loads(row["days_json"]) if row["days_json"] else None,
            "adequacy": json.loads(row["adequacy_json"]) if row["adequacy_json"] else None,
        }
    out = dict(document)
    out["plan_id"] = row["plan_id"]
    out["saved_at"] = row["created_at"]
    return out


def list_plans(patient_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Stored plan summaries (newest first), optionally for one patient."""
    sql = "SELECT * FROM plans"
    params: tuple[Any, ...] = ()
    if patient_id is not None:
        sql += " WHERE patient_id = ?"
        params = (patient_id,)
    sql += " ORDER BY created_at DESC, plan_id DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_plan_summary(row) for row in rows]


def latest_plan_for_patient(patient_id: str) -> Optional[dict[str, Any]]:
    """The most recently stored plan summary for a patient, if any."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE patient_id = ? "
            "ORDER BY created_at DESC, plan_id DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
    return _plan_summary(row) if row is not None else None


# ---------------------------------------------------------------------------
# Meal logs (same semantics as backend.app.adherence.store)
# ---------------------------------------------------------------------------


def put_log(
    patient_id: str,
    date: str,
    meal: str,
    dish_id: str,
    logged_at: Optional[str] = None,
    items: Optional[list[dict[str, Any]]] = None,
) -> dict[str, str]:
    """Insert or replace the log for one (patient, date, meal) slot."""
    entry = {
        "patient_id": patient_id,
        "date": date,
        "meal": meal,
        "dish_id": dish_id,
        "logged_at": logged_at or _utcnow(),
    }
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO meal_logs (patient_id, date, meal, dish_id, logged_at, items_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, date, meal) DO UPDATE SET
                dish_id = excluded.dish_id,
                logged_at = excluded.logged_at,
                items_json = excluded.items_json
            """,
            (entry["patient_id"], entry["date"], entry["meal"],
             entry["dish_id"], entry["logged_at"], json.dumps(items) if items else None),
        )
    return {**entry, **({"items": items} if items else {})}


def get_log(patient_id: str, date: str, meal: str) -> Optional[dict[str, str]]:
    """Return the log for one slot, or ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM meal_logs WHERE patient_id = ? AND date = ? AND meal = ?",
            (patient_id, date, meal),
        ).fetchone()
    if row is None:
        return None
    return {
        "patient_id": row["patient_id"],
        "date": row["date"],
        "meal": row["meal"],
        "dish_id": row["dish_id"],
        "logged_at": row["logged_at"],
        **({"items": json.loads(row["items_json"])} if row["items_json"] else {}),
    }


def list_logs(
    patient_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, str]]:
    """All logs for a patient, chronological (date, then meal order).

    ``date_from`` / ``date_to`` are inclusive ISO date bounds.
    """
    sql = "SELECT * FROM meal_logs WHERE patient_id = ?"
    params: list[Any] = [patient_id]
    if date_from is not None:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND date <= ?"
        params.append(date_to)
    sql += """
        ORDER BY date ASC,
                 CASE meal
                     WHEN 'breakfast' THEN 0
                     WHEN 'lunch' THEN 1
                     WHEN 'dinner' THEN 2
                     ELSE 99
                 END ASC
    """
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "patient_id": row["patient_id"],
            "date": row["date"],
            "meal": row["meal"],
            "dish_id": row["dish_id"],
            "logged_at": row["logged_at"],
            **({"items": json.loads(row["items_json"])} if row["items_json"] else {}),
        }
        for row in rows
    ]


def delete_logs_for_patient(patient_id: str) -> int:
    """Remove every log for a patient; returns the number deleted."""
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM meal_logs WHERE patient_id = ?", (patient_id,)
        )
        conn.commit()
        return int(cur.rowcount)


def count_logs(patient_id: Optional[str] = None) -> int:
    """Number of stored logs (optionally for one patient)."""
    sql = "SELECT COUNT(*) AS n FROM meal_logs"
    params: tuple[Any, ...] = ()
    if patient_id is not None:
        sql += " WHERE patient_id = ?"
        params = (patient_id,)
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["n"])


def clear_logs() -> None:
    """Delete every meal log (test/prototype helper)."""
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM meal_logs")
        conn.commit()


# ---------------------------------------------------------------------------
# Envelope journal
# ---------------------------------------------------------------------------


def store_envelope(envelope: NutrientEnvelope, *, new_proposal: bool = False) -> None:
    """Atomically allocate proposal identity and append its durable snapshot."""
    with _LOCK, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if new_proposal:
            base = re.sub(r"-\d+$", "", envelope.envelope_id)
            envelope.envelope_id = _mint_id(conn, "envelope_journal", base + "-", "envelope_id")
            envelope.proposed_at = datetime.now(timezone.utc)
        from shared.provenance import attach_provenance

        attach_provenance(envelope)
        snapshot = envelope.model_dump(by_alias=True, mode="json")
        conn.execute(
            "INSERT INTO envelope_journal "
            "(event, envelope_id, patient_id, version, status, snapshot_json, effective_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (envelope.status.value, envelope.envelope_id, envelope.patient_id,
             envelope.version, envelope.status.value, json.dumps(snapshot), _today()),
        )


def current_envelopes() -> list[NutrientEnvelope]:
    """Latest lifecycle snapshot per id; disk is authoritative across workers."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT snapshot_json FROM envelope_journal WHERE id IN "
            "(SELECT MAX(id) FROM envelope_journal GROUP BY envelope_id) ORDER BY id"
        ).fetchall()
    return [NutrientEnvelope.model_validate(json.loads(row[0])) for row in rows]


def save_patient(record: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO patients VALUES (?, ?) ON CONFLICT(patient_id) "
            "DO UPDATE SET document_json = excluded.document_json",
            (record["patient_id"], json.dumps(record)),
        )


def saved_patients() -> dict[str, dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM patients").fetchall()
    return {row["patient_id"]: json.loads(row["document_json"]) for row in rows}


def journal_envelope(
    envelope: NutrientEnvelope | dict[str, Any],
    event: Optional[str] = None,
    effective_at: Optional[str] = None,
) -> int:
    """Append one lifecycle row for ``envelope``; returns the journal id.

    ``envelope`` may be a :class:`NutrientEnvelope` or an already-dumped
    mapping; the **full snapshot** (``model_dump(by_alias=True, mode="json")``)
    is stored per row so any historical version can be reconstructed.
    ``event`` labels the lifecycle transition (defaults to the envelope
    status); ``effective_at`` is the ISO date from which the envelope governs
    the patient (defaults to today) and may carry a full timestamp — only the
    first 10 characters (the calendar date) participate in
    :func:`envelope_effective_at` comparisons.
    """
    if isinstance(envelope, dict):
        envelope = NutrientEnvelope.model_validate(envelope)
    snapshot = envelope.model_dump(by_alias=True, mode="json")
    status = (
        envelope.status.value
        if hasattr(envelope.status, "value")
        else str(envelope.status)
    )
    effective_at = effective_at or _today()
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO envelope_journal
                (event, envelope_id, patient_id, version, status,
                 snapshot_json, effective_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event or status,
                envelope.envelope_id,
                envelope.patient_id,
                int(envelope.version),
                status,
                json.dumps(snapshot),
                effective_at,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def envelope_effective_at(
    patient_id: str, iso_date: str
) -> Optional[NutrientEnvelope]:
    """Reconstruct the envelope effective for ``patient_id`` on ``iso_date``.

    The latest journalled APPROVED snapshot whose ``effective_at`` calendar date is
    less than or equal to ``iso_date`` wins (ties broken by the newest journal
    row). Returns ``None`` when no envelope was in force yet.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM envelope_journal
            WHERE patient_id = ? AND substr(effective_at, 1, 10) <= ? AND status = 'APPROVED'
            ORDER BY effective_at DESC, id DESC
            LIMIT 1
            """,
            (patient_id, iso_date),
        ).fetchone()
    if row is None:
        return None
    return NutrientEnvelope.model_validate(json.loads(row["snapshot_json"]))


def list_envelope_history(patient_id: str) -> list[dict[str, Any]]:
    """All journal rows for a patient, oldest first, snapshots parsed."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM envelope_journal WHERE patient_id = ? ORDER BY id ASC",
            (patient_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "event": row["event"],
            "envelope_id": row["envelope_id"],
            "patient_id": row["patient_id"],
            "version": int(row["version"]),
            "status": row["status"],
            "effective_at": row["effective_at"],
            "snapshot": json.loads(row["snapshot_json"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def add_observation(
    patient_id: str,
    metric: str,
    value: float,
    unit: Optional[str] = None,
    source: Optional[str] = None,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Record one clinical observation; returns the stored row.

    ``observed_at`` defaults to today (ISO date); ``recorded_at`` is always the
    wall-clock UTC receipt time. Observation ids are sequential per patient
    (``OBS-<patient_id>-001``, ...) and never reused.
    """
    observed_at = observed_at or _today()
    recorded_at = _utcnow()
    with _LOCK, _connect() as conn:
        observation_id = _mint_id(
            conn, "observations", f"OBS-{patient_id}-", "observation_id"
        )
        conn.execute(
            """
            INSERT INTO observations
                (observation_id, patient_id, metric, value, unit, source,
                 observed_at, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (observation_id, patient_id, metric, float(value), unit, source,
             observed_at, recorded_at),
        )
    return {
        "observation_id": observation_id,
        "patient_id": patient_id,
        "metric": metric,
        "value": float(value),
        "unit": unit,
        "source": source,
        "observed_at": observed_at,
        "recorded_at": recorded_at,
    }


def list_observations(patient_id: str) -> list[dict[str, Any]]:
    """All observations for a patient, chronological (observed_at, receipt)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM observations WHERE patient_id = ?
            ORDER BY observed_at ASC, recorded_at ASC, observation_id ASC
            """,
            (patient_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------


def save_simulation(
    patient_id: str,
    base_envelope_id: str,
    proposed_targets: list[dict[str, Any]] | dict[str, Any],
    comparison: Optional[dict[str, Any]] = None,
    status: str = "OPEN",
    created_at: Optional[str] = None,
) -> str:
    """Persist one what-if simulation; returns the minted simulation id."""
    created_at = created_at or _utcnow()
    with _LOCK, _connect() as conn:
        simulation_id = _mint_id(
            conn, "simulations", f"SIM-{patient_id}-", "simulation_id"
        )
        conn.execute(
            """
            INSERT INTO simulations
                (simulation_id, patient_id, base_envelope_id,
                 proposed_targets_json, comparison_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                simulation_id,
                patient_id,
                base_envelope_id,
                json.dumps(proposed_targets),
                json.dumps(comparison) if comparison is not None else None,
                status,
                created_at,
            ),
        )
    return simulation_id


def list_simulations(patient_id: str) -> list[dict[str, Any]]:
    """All simulations for a patient, oldest first, JSON fields parsed."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM simulations WHERE patient_id = ? "
            "ORDER BY created_at ASC, simulation_id ASC",
            (patient_id,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["proposed_targets"] = json.loads(row["proposed_targets_json"])
        item["comparison"] = (
            json.loads(row["comparison_json"]) if row["comparison_json"] else None
        )
        del item["proposed_targets_json"]
        del item["comparison_json"]
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "review_id": row["review_id"],
        "patient_id": row["patient_id"],
        "source": row["source"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "acknowledged_at": row["acknowledged_at"],
        "action": json.loads(row["action_json"]) if row["action_json"] else None,
        "linked_envelope_id": row["linked_envelope_id"],
    }


def create_review_item(
    patient_id: str,
    source: str,
    payload: dict[str, Any],
    created_at: Optional[str] = None,
    review_id: Optional[str] = None,
) -> str:
    """Enqueue one clinician review item; returns the review id.

    By default a sequential ``REV-<patient_id>-<NNN>`` id is minted. When
    ``review_id`` is supplied (the review queue's deterministic sha1 ids), it
    is used verbatim and the insert is skipped when a row with that id already
    exists — so repeated derivations of the same condition map to the same row
    idempotently.
    """
    created_at = created_at or _utcnow()
    with _LOCK, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if review_id is None:
            review_id = _mint_id(conn, "review_items", f"REV-{patient_id}-", "review_id")
        else:
            exists = conn.execute(
                "SELECT 1 FROM review_items WHERE review_id = ?", (review_id,)
            ).fetchone()
            if exists is not None:
                return review_id
        conn.execute(
            """
            INSERT INTO review_items
                (review_id, patient_id, source, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, 'OPEN', ?)
            """,
            (review_id, patient_id, source, json.dumps(payload), created_at),
        )
    return review_id


def list_review_items(
    status: Optional[str] = None,
    patient_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Review items (oldest first), optionally filtered by status and patient."""
    sql = "SELECT * FROM review_items"
    clauses, params = [], []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if patient_id is not None:
        clauses.append("patient_id = ?")
        params.append(patient_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at ASC, review_id ASC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_review_row(row) for row in rows]


def get_review_item(review_id: str) -> Optional[dict[str, Any]]:
    """One review item by id, or ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
    return _review_row(row) if row is not None else None


def acknowledge_review_item(review_id: str) -> Optional[dict[str, Any]]:
    """Mark a review item ACKNOWLEDGED; returns the updated item or ``None``."""
    acknowledged_at = _utcnow()
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "UPDATE review_items SET status = 'ACKNOWLEDGED', acknowledged_at = ? "
            "WHERE review_id = ?",
            (acknowledged_at, review_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
    return _review_row(row)


def record_review_action(
    review_id: str,
    action: str,
    note: Optional[str] = None,
    linked_envelope_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Record the clinician's action on a review item; returns the item.

    The action payload (``{action, note, linked_envelope_id, recorded_at}``) is
    stored verbatim in ``action_json`` and the item moves to
    ``ACTION_RECORDED``.
    """
    action_payload = {
        "action": action,
        "note": note,
        "linked_envelope_id": linked_envelope_id,
        "recorded_at": _utcnow(),
    }
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "UPDATE review_items SET status = 'ACTION_RECORDED', action_json = ?, "
            "linked_envelope_id = COALESCE(?, linked_envelope_id) "
            "WHERE review_id = ?",
            (json.dumps(action_payload), linked_envelope_id, review_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
    return _review_row(row)


# ---------------------------------------------------------------------------
# Test / maintenance helpers
# ---------------------------------------------------------------------------


def clear_all() -> None:
    """Delete every row from every table (test helper; schema is kept)."""
    with _LOCK, _connect() as conn:
        for table in (
            "plans", "meal_logs", "envelope_journal", "observations",
            "simulations", "review_items", "patients",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
