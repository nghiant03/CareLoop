"""Isolate tests from live URLs; provision only uniquely named PostgreSQL databases."""

import os
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

for _prefix in ("CARELOOP_APP", "CARELOOP_KNOWLEDGE"):
    for _suffix in ("_DB", "_DATABASE_URL", "_DATABASE_URL_FILE"):
        os.environ.pop(_prefix + _suffix, None)
os.environ["CARELOOP_APPROVAL_MODE"] = "clinician"
os.environ["CARELOOP_KNOWLEDGE_MODE"] = "fixtures"
os.environ.pop("CARELOOP_KNOWLEDGE_RELEASE", None)


@pytest.fixture(scope="session")
def pg_database_factory():
    """Require an explicit admin test URL; never clear a configured live database."""
    from backend.storage import postgres
    from backend.storage.migrate import initialize_database

    base = os.environ.get("CARELOOP_TEST_POSTGRES_URL")
    if not base:
        pytest.skip("CARELOOP_TEST_POSTGRES_URL not set; PostgreSQL integration not exercised")
    if not postgres.is_postgres(base):
        pytest.fail("CARELOOP_TEST_POSTGRES_URL must be a PostgreSQL URL")

    @contextmanager
    def databases():
        parts = urlsplit(base)
        names = {component: "careloop_test_" + component + "_" + uuid.uuid4().hex
                 for component in ("clinical", "knowledge")}
        urls = {component: urlunsplit(parts._replace(path="/" + name))
                for component, name in names.items()}
        created = []
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as admin:
            try:
                for component, name in names.items():
                    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                    created.append(name)
                    initialize_database(urls[component], component)
                yield urls
            finally:
                for url in urls.values():
                    pool = postgres._POOLS.pop(url, None)
                    if pool:
                        pool.close()
                for name in created:
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

    return databases


@pytest.fixture
def pg_databases(pg_database_factory):
    with pg_database_factory() as urls:
        yield urls


@pytest.fixture(scope="session")
def clinical_test_database(pg_database_factory):
    with pg_database_factory() as urls:
        os.environ["CARELOOP_APP_DATABASE_URL"] = urls["clinical"]
        try:
            yield urls["clinical"]
        finally:
            os.environ.pop("CARELOOP_APP_DATABASE_URL", None)
