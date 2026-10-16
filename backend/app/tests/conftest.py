"""Shared fixtures for the ``backend.app.tests`` suite.

Repository-root fixtures create a disposable PostgreSQL database from the
explicit test admin URL, never a deployment URL. The compatibility envelope
cache is cleared before backend tests begin.
"""

from __future__ import annotations

import pytest

from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE


@pytest.fixture(scope="session", autouse=True)
def _fresh_app_stores(clinical_test_database):
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
