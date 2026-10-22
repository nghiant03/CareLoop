import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql


def _map_legacy_test_arg(arg: str, repo_root: Path, tests_dir: Path) -> str:
    if arg.startswith("-"):
        return arg
    path_part, sep, node_part = arg.partition("::")
    norm = path_part.rstrip("/")
    if norm == "backend/app/tests" or norm.startswith("backend/app/tests/"):
        mapped = "tests/backend/app" + norm[len("backend/app/tests"):]
        if (repo_root / mapped).exists():
            return mapped + (sep + node_part if sep else "")
    if norm in ("rules", "backend", "evaluation", "shared") or norm.startswith(
        ("rules/", "backend/", "evaluation/", "shared/")
    ):
        cand = tests_dir / norm
        if cand.exists():
            return str(cand.relative_to(repo_root)) + (sep + node_part if sep else "")
    return arg


def pytest_load_initial_conftests(early_config, parser, args):
    repo_root = Path(__file__).resolve().parent
    tests_dir = repo_root / "tests"
    for idx, arg in enumerate(args):
        args[idx] = _map_legacy_test_arg(arg, repo_root, tests_dir)
    file_or_dir = getattr(early_config.known_args_namespace, "file_or_dir", None)
    if isinstance(file_or_dir, list):
        for idx, arg in enumerate(file_or_dir):
            file_or_dir[idx] = _map_legacy_test_arg(arg, repo_root, tests_dir)


def pytest_configure(config):
    repo_root = Path(__file__).resolve().parent
    tests_dir = repo_root / "tests"
    for idx, arg in enumerate(config.args):
        config.args[idx] = _map_legacy_test_arg(arg, repo_root, tests_dir)
    file_or_dir = getattr(config.option, "file_or_dir", None)
    if isinstance(file_or_dir, list):
        for idx, arg in enumerate(file_or_dir):
            file_or_dir[idx] = _map_legacy_test_arg(arg, repo_root, tests_dir)

for _prefix in ("CARELOOP_APP", "CARELOOP_KNOWLEDGE"):
    for _suffix in ("_DB", "_DATABASE_URL"):
        os.environ.pop(_prefix + _suffix, None)
os.environ["CARELOOP_APPROVAL_MODE"] = "clinician"
os.environ["CARELOOP_KNOWLEDGE_MODE"] = "fixtures"
os.environ.pop("CARELOOP_KNOWLEDGE_RELEASE", None)


@pytest.fixture(scope="session")
def pg_database_factory():
    """Use only an explicit test admin URL and uniquely named disposable databases."""
    from backend.storage import postgres
    from backend.storage.migrate import initialize_database

    base = os.environ.get("CARELOOP_TEST_POSTGRES_URL") or ""
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
