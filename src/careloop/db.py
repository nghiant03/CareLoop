"""Explicit, transactional schema setup; the API never migrates on startup."""

import hashlib
import os
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    return os.environ["CARELOOP_DATABASE_URL"]


def migrate(url: str) -> None:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(81723001)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name text PRIMARY KEY, checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        for migration in sorted(
            files("careloop").joinpath("migrations").iterdir(), key=lambda item: item.name
        ):
            if not migration.name.endswith(".sql"):
                continue
            content = migration.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()
            previous = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE name = %s", (migration.name,)
            ).fetchone()
            if previous:
                if previous["checksum"] != checksum:
                    raise RuntimeError(f"Applied migration changed: {migration.name}")
                continue
            conn.execute(content)
            conn.execute(
                "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
                (migration.name, checksum),
            )


if __name__ == "__main__":
    migrate(database_url())
