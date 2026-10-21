"""Explicit PostgreSQL schema initialization; never called by runtime startup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from psycopg import sql

from backend.storage.postgres import (
    _WRITE_LOCKS,
    check_schema,
    database_url,
    storage_row,
)

CLINICAL_TABLES = ("patients", "plans", "meal_logs", "envelope_journal", "observations", "simulations", "review_items")
KNOWLEDGE_TABLES = ("knowledge_drafts", "knowledge_revisions", "knowledge_reviews", "knowledge_releases", "knowledge_events")


def tables_for(component: str) -> tuple[str, ...]:
    if component not in {"clinical", "knowledge"}:
        raise ValueError("component must be clinical or knowledge")
    return CLINICAL_TABLES if component == "clinical" else KNOWLEDGE_TABLES


def schema_sql(component: str) -> str:
    """Load a frozen versioned PostgreSQL migration."""
    tables_for(component)
    return (Path(__file__).with_name("migrations") / f"001_{component}.sql").read_text(encoding="utf-8")


def initialize_database(url: str, component: str) -> dict:
    """Apply version 1 as admin; check existing databases without recreating them."""
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
        conn.execute(schema_sql(component))  # pyrefly: ignore[no-matching-overload]
        conn.execute("CREATE TABLE careloop_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        conn.execute("INSERT INTO careloop_schema VALUES (%s,1)", (component,))
        # Retain the v1 metadata table for compatibility with existing databases.
        # No SQLite import command or runtime backend remains.
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
        roles = ("careloop_app",) if component == "clinical" else ("careloop_knowledge_reader", "careloop_knowledge_operator")
        for role in roles:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("REVOKE ALL ON careloop_schema, careloop_imports FROM {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT SELECT ON careloop_schema TO {}").format(sql.Identifier(role)))
    return {"component": component, "schema_version": 1, "initialized": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init",))
    parser.add_argument("--component", choices=("clinical", "knowledge", "both"), required=True)
    args = parser.parse_args(argv)
    try:
        components = ("clinical", "knowledge") if args.component == "both" else (args.component,)
        results = []
        for component in components:
            url = database_url(component)
            if url is None:
                raise ValueError(f"configure the {component} PostgreSQL DATABASE_URL or _FILE")
            results.append(initialize_database(url, component))
    except psycopg.Error:
        parser.exit(1, "PostgreSQL migration failed. Inspect server access/schema without sharing credentials.\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Migration refused: {exc}\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
