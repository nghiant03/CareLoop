"""Storage relocation must preserve clinical state and never replace existing data."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core import persistence
from backend.app.core.migrate_storage import copy_database, main
from backend.app.main import app
from backend.storage_paths import default_app_db_path


def test_default_is_external_and_configuration_is_lazy(monkeypatch, tmp_path):
    monkeypatch.delenv("CARELOOP_APP_DB")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(persistence, "_LEGACY_DB", tmp_path / "absent.sqlite3")
    expected = tmp_path / "state" / "careloop" / "careloop_app.sqlite3"
    assert persistence.db_path() == str(expected)
    assert not expected.parent.exists()
    monkeypatch.setenv("CARELOOP_APP_DB", str(tmp_path / "explicit.sqlite3"))
    assert persistence.db_path() == str(tmp_path / "explicit.sqlite3")
    monkeypatch.setenv("XDG_STATE_HOME", "relative-state")
    with pytest.raises(ValueError, match="absolute"):
        default_app_db_path()


def test_home_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_app_db_path() == tmp_path / ".local/state/careloop/careloop_app.sqlite3"


def test_legacy_database_blocks_silent_empty_start(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    legacy.write_bytes(b"preserved")
    monkeypatch.setattr(persistence, "_LEGACY_DB", legacy)
    monkeypatch.delenv("CARELOOP_APP_DB")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with pytest.raises(RuntimeError, match="Legacy CareLoop database"):
        with TestClient(app):
            pass
    assert legacy.read_bytes() == b"preserved"
    assert not default_app_db_path().exists()
    monkeypatch.setenv("CARELOOP_APP_DB", str(legacy))
    assert persistence.db_path() == str(legacy)


def test_new_database_permissions_and_unusable_storage(monkeypatch, tmp_path):
    database = tmp_path / "private" / "app.sqlite3"
    monkeypatch.setenv("CARELOOP_APP_DB", str(database))
    persistence.init_db()
    if os.name == "posix":
        assert database.stat().st_mode & 0o777 == 0o600
        assert database.parent.stat().st_mode & 0o777 == 0o700
    monkeypatch.setenv("CARELOOP_APP_DB", str(database / "invalid.sqlite3"))
    with pytest.raises(OSError):
        with TestClient(app):
            pass


def test_copy_includes_uncheckpointed_wal_and_refuses_overwrite(tmp_path):
    source, destination = tmp_path / "source.sqlite3", tmp_path / "external/copy.sqlite3"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE snapshots (document TEXT)")
        connection.execute("INSERT INTO snapshots VALUES (?)", ('{"revision": 7}',))
        connection.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        assert copy_database(source, destination) == destination
        with closing(sqlite3.connect(destination)) as copied:
            assert copied.execute("SELECT document FROM snapshots").fetchall() == [('{"revision": 7}',)]
        before = destination.read_bytes()
        with pytest.raises(FileExistsError):
            copy_database(source, destination)
        assert destination.read_bytes() == before
        assert connection.execute("SELECT count(*) FROM snapshots").fetchone() == (1,)
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600


def test_copy_failure_keeps_source_and_cleans_partial_output(tmp_path):
    source, destination = tmp_path / "invalid.sqlite3", tmp_path / "output/copy.sqlite3"
    source.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        copy_database(source, destination)
    assert source.read_bytes() == b"not a database"
    assert not destination.exists()
    assert not list(destination.parent.iterdir())
    with pytest.raises(FileNotFoundError):
        copy_database(tmp_path / "missing.sqlite3", destination)
    assert not (tmp_path / "missing.sqlite3").exists()
    destination.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        copy_database(source, destination)


def test_migration_preserves_approval_history_and_embedded_traces(monkeypatch, tmp_path):
    source = tmp_path / "legacy.sqlite3"
    destination = tmp_path / "external/app.sqlite3"
    monkeypatch.setenv("CARELOOP_APP_DB", str(source))
    with TestClient(app) as client:
        proposal = client.post("/rules/run", json={"patient_id": "P0005"}).json()["envelope"]
        envelope_id = proposal["envelope_id"]
        response = client.post(f"/envelopes/{envelope_id}/approve", json={
            "approved_by": "Dr.StorageTest", "expected_revision": proposal["lifecycle_revision"],
        })
        assert response.status_code == 200, response.text
        approved = client.get(f"/envelopes/{envelope_id}").json()
        explanation = client.get(f"/envelopes/{envelope_id}/explanation").json()
    with closing(sqlite3.connect(source)) as connection:
        before = list(connection.iterdump())
    copy_database(source, destination)
    with closing(sqlite3.connect(destination)) as connection:
        assert list(connection.iterdump()) == before
    monkeypatch.setenv("CARELOOP_APP_DB", str(destination))
    with TestClient(app) as client:
        assert client.get(f"/envelopes/{envelope_id}").json() == approved
        assert client.get(f"/envelopes/{envelope_id}/explanation").json() == explanation
        assert approved["status"] == "APPROVED"
        assert approved["fired_rules"]


def test_cli_uses_environment_destination(monkeypatch, tmp_path):
    source, destination = tmp_path / "source.sqlite3", tmp_path / "copy.sqlite3"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
    monkeypatch.setenv("CARELOOP_APP_DB", str(destination))
    assert main(["--source", str(source)]) == 0
    assert source.exists() and destination.exists()
    with pytest.raises(SystemExit) as error:
        main(["--source", str(source)])
    assert error.value.code == 1
