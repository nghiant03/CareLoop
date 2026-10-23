from contextlib import nullcontext
from threading import Event

from test_extraction import Provider

from careloop import bootstrap
from careloop.foods.models import FoodBody
from careloop.inference import Settings


def fixtures(monkeypatch):
    body = FoodBody.model_validate(
        {
            "name": "Test food",
            "category": "Test",
            "nutrients": {"energy": 100},
            "portions": [{"id": "portion", "label": "Test portion", "grams": 100}],
            "provenance": {"kind": "manual", "source": "test://fixture", "notes": "Test only"},
        }
    )
    monkeypatch.setattr(bootstrap.ingestion, "acquire", lambda *a: ([("test", body)], {}, None))
    monkeypatch.setattr(
        bootstrap.acquisition,
        "SEEDS",
        [
            {"title": "Test guideline", "url": "https://www.who.int/test"},
        ],
    )
    monkeypatch.setattr(
        bootstrap.acquisition,
        "download",
        lambda url: (
            b"<h1>Nutrition</h1><p>Test recommendation</p>",
            {"content_type": "text/html", "final_url": url},
        ),
    )
    provider = Provider()
    monkeypatch.setattr(bootstrap, "InferenceClient", lambda settings: nullcontext(provider))
    monkeypatch.setattr(Settings, "load", lambda: provider.settings)
    return provider


def test_first_boot_imports_drafts_and_restart_does_not_duplicate(client, monkeypatch, tmp_path):
    provider = fixtures(monkeypatch)
    pool = client.app.state.pool
    bootstrap.run(pool, tmp_path, Event())
    first = client.get("/api/bootstrap").json()["jobs"]
    assert all(j["state"] == "completed" for j in first)
    assert provider.calls > 0
    calls = provider.calls
    bootstrap.run(pool, tmp_path, Event())
    assert provider.calls == calls
    assert client.get("/api/bootstrap").json()["jobs"] == first
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] == 1
        rules = conn.execute("SELECT * FROM evidence_rules").fetchall()
        assert rules and all(r["active_revision"] is None for r in rules)


def test_acquisition_failure_is_visible_and_restart_recovers(client, monkeypatch, tmp_path):
    fixtures(monkeypatch)
    download = bootstrap.acquisition.download

    def fail(url):
        raise OSError("Do not expose upstream secrets")

    monkeypatch.setattr(bootstrap.acquisition, "download", fail)
    bootstrap.run(client.app.state.pool, tmp_path, Event())
    result = client.get("/api/bootstrap")
    assert "upstream secrets" not in result.text
    assert any(j["state"] == "failed" for j in result.json()["jobs"])
    monkeypatch.setattr(bootstrap.acquisition, "download", download)
    bootstrap.run(client.app.state.pool, tmp_path, Event())
    assert all(j["state"] == "completed" for j in client.get("/api/bootstrap").json()["jobs"])


def test_provider_failure_is_retained_without_repeat_calls(client, monkeypatch, tmp_path):
    provider = fixtures(monkeypatch)
    provider.error = "Provider failed"
    bootstrap.run(client.app.state.pool, tmp_path, Event())
    calls = provider.calls
    bootstrap.run(client.app.state.pool, tmp_path, Event())
    assert provider.calls == calls
    jobs = client.get("/api/bootstrap").json()["jobs"]
    assert any(j["state"] == "failed" and "retry explicitly" in j["error"] for j in jobs)


def test_other_worker_cannot_initialize_concurrently(client, monkeypatch, tmp_path):
    provider = fixtures(monkeypatch)
    pool = client.app.state.pool
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (bootstrap.LOCK,))
        try:
            bootstrap.run(pool, tmp_path, Event())
            assert not bootstrap.status(pool)
            assert provider.calls == 0
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (bootstrap.LOCK,))


def test_startup_launches_worker_and_stops_before_pool_closes(database, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from careloop.api import create_app

    started = Event()
    stopped = Event()

    def worker(pool, directory, stop):
        assert directory == str(tmp_path)
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        started.set()
        assert stop.wait(5)
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        stopped.set()

    monkeypatch.setenv("CARELOOP_BOOTSTRAP", "1")
    monkeypatch.setenv("CARELOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(bootstrap, "run", worker)
    with TestClient(create_app(database)) as client:
        assert started.wait(5)
        assert client.get("/api/bootstrap").json()["enabled"] is True
        assert client.get("/api/health").status_code == 200
    assert stopped.is_set()


def test_parser_upgrade_refreshes_retained_original_without_redownloading(
    client, monkeypatch, tmp_path
):
    fixtures(monkeypatch)
    pool = client.app.state.pool
    bootstrap.run(pool, tmp_path, Event())
    original = client.get("/api/evidence/sources").json()[0]
    monkeypatch.setattr(bootstrap, "PARSER_VERSION", "test-parser-upgrade")

    def unexpected_download(url):
        raise AssertionError("Must reuse the retained original")

    monkeypatch.setattr(bootstrap.acquisition, "download", unexpected_download)
    bootstrap.run(pool, tmp_path, Event())
    sources = client.get("/api/evidence/sources").json()
    assert len(sources) == 2
    newer = next(s for s in sources if s["id"] != original["id"])
    detail = client.get(f"/api/evidence/sources/{newer['id']}").json()
    assert detail["document"]["metadata"]["reparsed_from"] == original["id"]
    assert client.get(f"/api/evidence/sources/{original['id']}").status_code == 200
    bootstrap.run(pool, tmp_path, Event())
    assert len(client.get("/api/evidence/sources").json()) == 2
