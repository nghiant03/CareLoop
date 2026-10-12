"""Shared fixtures for the ``backend.app.tests`` suite.

When ``CARELOOP_APP_DB`` is absent, select a temporary database before store
calls. Repository-root fixtures normally select it first; backend-only pytest
roots may not load those fixtures. An explicitly configured path is respected
and must already be isolated: the session fixture deletes all its records.
It also clears the compatibility envelope cache before backend tests begin.
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


@pytest.fixture()
def lenient_client():
    """TestClient that returns 500 responses instead of raising them.

    Only the fault-injection tests need the unhandled-error response body;
    every other test keeps the shared strict client.
    """
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
