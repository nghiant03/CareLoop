from __future__ import annotations

import pytest

from backend.app.core import persistence
from backend.app.core.approval_gate import ENVELOPE_STORE


@pytest.fixture(scope="session", autouse=True)
def _fresh_app_stores(clinical_test_database):
    persistence.init_db()
    persistence.clear_all()
    ENVELOPE_STORE.clear()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def lenient_client():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
