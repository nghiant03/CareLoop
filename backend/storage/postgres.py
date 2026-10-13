"""Small PostgreSQL boundary for the existing storage queries and row contracts.

SQL remains parameterized. JSON snapshots stay TEXT to preserve their exact
payload/hash contract; relational columns carry lookup and workflow state.
Runtime verifies schema versions but never creates or migrates tables.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from threading import Lock

import psycopg
from psycopg_pool import ConnectionPool

_POOLS: dict[str, ConnectionPool] = {}
_POOL_LOCK = Lock()
# Preserve the existing write-reservation semantics across processes/hosts.
# This conservative first migration serializes writers per database domain,
# not readers. Finer-grained locking needs its own contention/regression study.
_WRITE_LOCKS = {"clinical": 1129070593, "knowledge": 1129070594}
_SQL_TOKENS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/|\?", re.S)


def database_url(component: str) -> str | None:
    """Read a URL or a Docker-secret file; reject ambiguous or malformed settings.

    Credentials are never returned in diagnostics. A configured but unavailable
    PostgreSQL database must not fall back to SQLite.
    """
    if component not in _WRITE_LOCKS:
        raise ValueError("database component must be clinical or knowledge")
    prefix = "CARELOOP_APP" if component == "clinical" else "CARELOOP_KNOWLEDGE"
    variable = f"{prefix}_DATABASE_URL"
    value, filename = os.environ.get(variable), os.environ.get(variable + "_FILE")
    if value is not None and filename is not None:
        raise ValueError(f"Set only {variable} or {variable}_FILE")
    if filename is not None:
        value = Path(filename).read_text(encoding="utf-8").strip()
    if value is not None and not value.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"{variable} must contain a PostgreSQL URL")
    return value


def is_postgres(value: str | Path) -> bool:
    return str(value).startswith(("postgresql://", "postgres://"))


def bind_sql(sql: str) -> str:
    """Adapt repository qmark value placeholders, excluding quoted SQL/comments.

    This is not a SQLite dialect translator. Only the storage layer's portable
    SQL is accepted; schema migration SQL is authored/executed separately.
    """
    return _SQL_TOKENS.sub(lambda match: "%s" if match[0] == "?" else match[0], sql.replace("%", "%%"))


class StorageRow(dict):
    """Support the existing named/positional row reads without changing payloads."""

    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def storage_row(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: StorageRow(zip(names, values))


def _pool(url: str) -> ConnectionPool:
    with _POOL_LOCK:
        if url not in _POOLS:
            maximum = int(os.environ.get("CARELOOP_DB_POOL_MAX_SIZE", "5"))
            if maximum < 1:
                raise ValueError("CARELOOP_DB_POOL_MAX_SIZE must be positive")
            _POOLS[url] = ConnectionPool(url, min_size=0, max_size=maximum, open=True, timeout=10,
                                         kwargs={"row_factory": storage_row, "connect_timeout": 5})
        return _POOLS[url]


def check_schema(connection, component: str) -> None:
    try:
        rows = connection.execute("SELECT component, version FROM careloop_schema").fetchall()
    except psycopg.errors.UndefinedTable:
        raise RuntimeError("PostgreSQL schema is not initialized; run backend.storage.migrate init") from None
    if len(rows) != 1 or rows[0]["component"] != component or rows[0]["version"] != 1:
        raise RuntimeError(f"Wrong or unsupported PostgreSQL {component} schema")


class PostgresConnection:
    """Pooled transaction with explicit write reservations and optional read-only mode.

    BEGIN IMMEDIATE in legacy callers requests a database-scoped transaction
    advisory lock. All other mutations take the same lock before executing,
    including single-statement updates that might race a check-and-append.
    Nothing retries an ambiguous commit automatically.
    """

    def __init__(self, url: str, component: str, *, readonly: bool = False):
        self.component, self.readonly = component, readonly
        self._reserved = False
        self._closed = False
        self._context = _pool(url).connection()
        self.raw = self._context.__enter__()
        try:
            check_schema(self.raw, component)
            self.raw.commit()
            if readonly:
                self.raw.execute("SET TRANSACTION READ ONLY")
        except BaseException:
            self._closed = True
            self._context.__exit__(*sys.exc_info())
            raise

    @property
    def in_transaction(self) -> bool:
        # Legacy callers ask this to determine whether a write reservation exists,
        # not whether PostgreSQL has started a read-only transaction implicitly.
        return self._reserved

    def reserve_write(self):
        if self.readonly:
            raise ValueError("read-only knowledge connection cannot reserve writes")
        if not self._reserved:
            self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (_WRITE_LOCKS[self.component],))
            self._reserved = True

    def execute(self, sql: str, params=None):
        operation = sql.lstrip().split(None, 1)[0].upper()
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            self.reserve_write()
            return self.raw.execute("SELECT 1")
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            self.reserve_write()
        if params is None:
            return self.raw.execute(sql)
        return self.raw.execute(bind_sql(sql), params)

    def commit(self):
        self.raw.commit()
        self._reserved = False
        if self.readonly:
            self.raw.execute("SET TRANSACTION READ ONLY")

    def close(self):
        if not self._closed:
            self._closed = True
            self._context.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if not self._closed:
            self._closed = True
            return self._context.__exit__(*args)
