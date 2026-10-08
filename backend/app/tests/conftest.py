"""Shared fixtures for the ``backend.app.tests`` suite.

Isolation contract
------------------
Every pytest session runs against its **own** SQLite application database:
``CARELOOP_APP_DB`` is pointed at a fresh temp file before any store call
happens (the repo-root ``conftest.py`` normally sets it first; this module
repeats the guard so ``pytest backend`` — where the root conftest is not
collected — is isolated too). Because
``backend.app.core.persistence`` resolves the path lazily per call, setting
the env var here is sufficient regardless of import order.

A session-scoped autouse fixture additionally clears all persistent tables and
the in-memory envelope store at session start, so a stale database file (or a
leftover in-process state from another suite in the same session) can never
leak into a run.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

if not os.environ.get("CARELOOP_APP_DB"):
    _TMP_DB_DIR = tempfile.mkdtemp(prefix="careloop-backend-tests-")
    os.environ["CARELOOP_APP_DB"] = str(Path(_TMP_DB_DIR) / "careloop_app.sqlite3")

import pytest

from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE


@pytest.fixture(scope="session", autouse=True)
def _fresh_app_stores():
    """Fresh persistence tables + in-memory stores at session start."""
    persistence.init_db()
    persistence.clear_all()
    ENVELOPE_STORE.clear()
    yield


@pytest.fixture(scope="module")
def client():
    """Shared TestClient (lifespan included, so the KB warms up)."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as c:
        yield c