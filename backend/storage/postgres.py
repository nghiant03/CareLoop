"""Pooled PostgreSQL transactions with explicit write reservations."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from threading import Lock
from typing import Any

import psycopg
from psycopg import Connection, Cursor
from psycopg_pool import ConnectionPool

_POOLS: dict[str, ConnectionPool] = {}
_POOL_LOCK = Lock()
# Serialize writers per database while leaving readers independent.
_WRITE_LOCKS = {"clinical": 1129070593, "knowledge": 1129070594}
_SQL_TOKENS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/|\?", re.DOTALL)


def database_url(component: str) -> str | None:
    """Reject retired storage settings rather than silently abandon existing data."""
    if component not in _WRITE_LOCKS:
        raise ValueError("database component must be clinical or knowledge")
    prefix = "CARELOOP_APP" if component == "clinical" else "CARELOOP_KNOWLEDGE"
    if os.environ.get(prefix + "_DB") is not None:
        raise ValueError(f"{prefix}_DB is no longer supported; configure {prefix}_DATABASE_URL. Existing files are untouched.")
    variable = f"{prefix}_DATABASE_URL"
    if os.environ.get(variable + "_FILE") is not None:
        raise ValueError(f"{variable}_FILE is no longer supported; configure {variable} directly")
    value = os.environ.get(variable)
    if value is not None and not value.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"{variable} must contain a PostgreSQL URL")
    return value


def is_postgres(value: str | Path) -> bool:
    return str(value).startswith(("postgresql://", "postgres://"))


def bind_sql(sql: str) -> str:
    """Adapt value placeholders without translating SQL dialects."""
    return _SQL_TOKENS.sub(lambda match: "%s" if match[0] == "?" else match[0], sql.replace("%", "%%"))


class StorageRow(dict):
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
        raise RuntimeError("PostgreSQL schema is not initialized; the deployment setup task must finish before application startup") from None
    if len(rows) != 1 or rows[0]["component"] != component or rows[0]["version"] != 1:
        raise RuntimeError(f"Wrong or unsupported PostgreSQL {component} schema")


class PostgresConnection:
    """All writes share a database scoped advisory lock. Ambiguous commits are never retried automatically."""

    def __init__(self, url: str, component: str, *, readonly: bool = False):
        self.component, self.readonly = component, readonly
        self._reserved = False
        self._closed = False
        self._context = _pool(url).connection()
        # The pool guarantees StorageRow but exposes a broader static type.
        self.raw: Connection[StorageRow] = self._context.__enter__()  # pyrefly: ignore[bad-assignment]
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
        return self._reserved

    def reserve_write(self):
        if self.readonly:
            raise ValueError("read-only knowledge connection cannot reserve writes")
        if not self._reserved:
            self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (_WRITE_LOCKS[self.component],))
            self._reserved = True

    def execute(self, sql: str, params: Any = None) -> Cursor[StorageRow]:
        operation = sql.lstrip().split(None, 1)[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            self.reserve_write()
        # SQL text uses internal constants and values stay parameterized.
        if params is None:
            return self.raw.execute(sql)  # pyrefly: ignore[no-matching-overload]
        return self.raw.execute(bind_sql(sql), params)  # pyrefly: ignore[bad-argument-type]

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
