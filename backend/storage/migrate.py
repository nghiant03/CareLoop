"""Explicit PostgreSQL schema initialization and verified SQLite imports.

No live application startup calls this module. Each database import is atomic,
refuses populated targets, retains the source, and compares every stored column.
Clinical and knowledge databases are separate transactions, never an implied
cross-database atomic operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import psycopg
from psycopg import sql
from pydantic import ValidationError

from backend.storage.postgres import _WRITE_LOCKS, check_schema, database_url, storage_row

CLINICAL_TABLES = ("patients", "plans", "meal_logs", "envelope_journal", "observations", "simulations", "review_items")
KNOWLEDGE_TABLES = ("knowledge_drafts", "knowledge_revisions", "knowledge_reviews", "knowledge_releases", "knowledge_events")
_IDENTITIES = {"clinical": ("envelope_journal", "id"), "knowledge": ("knowledge_events", "event_id")}


def tables_for(component: str) -> tuple[str, ...]:
    if component not in {"clinical", "knowledge"}:
        raise ValueError("component must be clinical or knowledge")
    return CLINICAL_TABLES if component == "clinical" else KNOWLEDGE_TABLES


def schema_sql(component: str) -> str:
    """Load a frozen migration, independent of later legacy schema/code changes."""
    tables_for(component)
    return (Path(__file__).with_name("migrations") / f"001_{component}.sql").read_text(encoding="utf-8")


def initialize_database(url: str, component: str) -> dict:
    """Apply version 1 with an admin role; reject unrelated or newer databases.

    Existing version-1 databases are checked, not recreated. SQL DDL and version
    recording are in one transaction; initialization does not import patient data.
    """
    expected = set(tables_for(component)) | {"careloop_schema", "careloop_imports"}
    with psycopg.connect(url, row_factory=storage_row, connect_timeout=5) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_WRITE_LOCKS[component],))
        existing = {row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )}
        if existing:
            if existing != expected:
                raise ValueError("refusing to initialize an unrelated or incomplete PostgreSQL database")
            check_schema(conn, component)
            return {"component": component, "schema_version": 1, "initialized": False}
        conn.execute(schema_sql(component))
        conn.execute("CREATE TABLE careloop_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        conn.execute("INSERT INTO careloop_schema VALUES (%s,1)", (component,))
        conn.execute("""CREATE TABLE careloop_imports (
            source_digest TEXT PRIMARY KEY, source_path TEXT NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now(), counts_json TEXT NOT NULL
        )""")
        if component == "knowledge":
            conn.execute("""CREATE FUNCTION reject_knowledge_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'immutable knowledge journal' USING ERRCODE = '23514'; END;
            $$""")
            for table in KNOWLEDGE_TABLES:
                conn.execute(sql.SQL("CREATE TRIGGER {} BEFORE UPDATE OR DELETE OR TRUNCATE ON {} "
                                     "FOR EACH STATEMENT EXECUTE FUNCTION reject_knowledge_mutation()")
                             .format(sql.Identifier(table + "_immutable"), sql.Identifier(table)))
        # Default object grants from bootstrap must not authorize changing schema
        # version/import markers. Only the migration administrator owns these.
        roles = ("careloop_app",) if component == "clinical" else ("careloop_knowledge_reader", "careloop_knowledge_operator")
        for role in roles:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("REVOKE ALL ON careloop_schema, careloop_imports FROM {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT SELECT ON careloop_schema TO {}").format(sql.Identifier(role)))
    return {"component": component, "schema_version": 1, "initialized": True}


def row_digest(rows: list[dict]) -> str:
    """Hash a row multiset, retaining exact JSON/TEXT values and duplicate records."""
    encoded = sorted(json.dumps(dict(row), sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False) for row in rows)
    digest = hashlib.sha256()
    for row in encoded:
        payload = row.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def sqlite_snapshot(source: Path):
    """Take a read-only, WAL-aware snapshot without initializing/upgrading its source."""
    source = source.expanduser().resolve(strict=True)
    snapshot = sqlite3.connect(":memory:")
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            original.backup(snapshot)
        if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite source failed integrity check")
        if snapshot.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite source contains foreign-key violations")
        snapshot.row_factory = sqlite3.Row
        return snapshot
    except BaseException:
        snapshot.close()
        raise


def import_sqlite(source: Path, url: str, component: str, *, writers_stopped: bool = False) -> dict:
    """Copy all rows into an empty migrated database and verify before committing.

    writers_stopped is an operator attestation: this function cannot stop an
    external application. Old schemas may omit whole tables or meal items_json;
    any other unknown/missing columns are rejected, never silently discarded.
    Sources remain intact, including revision IDs and raw snapshot/citation JSON.
    """
    if not writers_stopped:
        raise ValueError("stop all source/target writers and confirm --writers-stopped before import")
    tables = tables_for(component)
    source = source.expanduser().resolve(strict=True)
    with closing(sqlite_snapshot(source)) as snapshot, psycopg.connect(url, row_factory=storage_row, connect_timeout=5) as conn:
        check_schema(conn, component)
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_WRITE_LOCKS[component],))
        conn.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(sql.SQL(", ").join(sql.Identifier(t) for t in tables)))
        if conn.execute("SELECT 1 FROM careloop_imports LIMIT 1").fetchone():
            raise ValueError("target already has an import record; refusing repeated import")
        for table in tables:
            if conn.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchone():
                raise ValueError("PostgreSQL target is populated; import refuses overwrites or merges")
        source_tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")
                         if not row[0].startswith("sqlite_")}
        if not source_tables:
            raise ValueError("SQLite source has no domain tables; refusing an empty unrelated source")
        if source_tables - set(tables):
            raise ValueError("SQLite source contains tables outside the selected domain")
        if component == "knowledge" and (source_tables != set(tables) or snapshot.execute("PRAGMA user_version").fetchone()[0] != 1):
            raise ValueError("unsupported/incomplete SQLite knowledge schema")
        counts, hashes = {}, {}
        for table in tables:
            columns = [row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))]
            source_columns = [row[1] for row in snapshot.execute(f'PRAGMA table_info("{table}")')] if table in source_tables else []
            if source_columns:
                missing = set(columns) - set(source_columns)
                if set(source_columns) - set(columns) or (missing and not (table == "meal_logs" and missing == {"items_json"})):
                    raise ValueError(f"unsupported source columns in {table}")
            rows = [dict(row) for row in snapshot.execute(f'SELECT * FROM "{table}"')] if source_columns else []
            for row in rows:
                for column in columns:
                    row.setdefault(column, None)
                for column, value in row.items():
                    if column.endswith("_json") and value is not None:
                        json.loads(value)
                if table == "envelope_journal":
                    from shared.envelope_schema import NutrientEnvelope

                    NutrientEnvelope.model_validate_json(row["snapshot_json"])
            if table == "knowledge_revisions":
                from backend.knowledge.validation import content_hash

                for row in rows:
                    if content_hash(json.loads(row["rules_json"])) != row["rules_hash"] or content_hash(json.loads(row["dishes_json"])) != row["dishes_hash"]:
                        raise ValueError("source knowledge revision checksum mismatch")
            insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns))
            with conn.cursor() as cursor:
                cursor.executemany(insert, [tuple(row[column] for column in columns) for row in rows])
            copied = conn.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()
            hashes[table] = row_digest(rows)
            if hashes[table] != row_digest(copied):
                raise ValueError(f"post-import verification failed for {table}; transaction rolled back")
            counts[table] = len(rows)
        table, column = _IDENTITIES[component]
        # Avoid setval's nontransactional side effect. Transactional RESTART keeps
        # a failed import from changing the next journal/event identity.
        maximum = conn.execute(sql.SQL("SELECT COALESCE(MAX({}),0) FROM {}").format(sql.Identifier(column), sql.Identifier(table))).fetchone()[0]
        conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN {} RESTART WITH {}").format(
            sql.Identifier(table), sql.Identifier(column), sql.Literal(maximum + 1)))
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        conn.execute("INSERT INTO careloop_imports(source_digest,source_path,counts_json) VALUES (%s,%s,%s)",
                     (digest, str(source), json.dumps(counts, sort_keys=True)))
    return {"component": component, "verified": True, "counts": counts, "table_hashes": hashes, "source_digest": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "import-sqlite"))
    parser.add_argument("--component", choices=("clinical", "knowledge", "both"), required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "import-sqlite" and (args.component == "both" or args.source is None):
            raise ValueError("import requires a single component and --source")
        components = ("clinical", "knowledge") if args.component == "both" else (args.component,)
        results = []
        for component in components:
            url = database_url(component)
            if url is None:
                raise ValueError(f"configure the {component} PostgreSQL DATABASE_URL or _FILE")
            if args.command == "init":
                results.append(initialize_database(url, component))
            else:
                results.append(import_sqlite(args.source, url, component, writers_stopped=args.writers_stopped))
    except ValidationError:
        parser.exit(1, "Migration refused: an envelope snapshot failed validation; source retained. Patient payloads omitted.\n")
    except psycopg.Error:
        parser.exit(1, "PostgreSQL migration failed; source retained. Inspect server access/schema without sharing credentials.\n")
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Migration refused: {exc}\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
