import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from careloop.api import create_app
from careloop.db import migrate


@pytest.fixture
def database():
    url = os.environ.get("CARELOOP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CARELOOP_TEST_DATABASE_URL or run tests/run_postgres.py")
    schema = "check_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(url, options=f"-csearch_path={schema}")
    try:
        migrate(scoped)
        yield scoped
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def client(database):
    with TestClient(create_app(database)) as client:
        yield client
