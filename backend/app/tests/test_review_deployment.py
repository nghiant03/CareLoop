"""Review deployment can start without a release but never serves clinical workflows."""

import json

from fastapi.testclient import TestClient
import pytest

from backend.app.deployment import create_app
from backend.app.review_preview import create_review_app
from backend.datasets.paths import dataset_path
from backend.knowledge.store import KnowledgeStore


@pytest.fixture
def review_store(pg_databases, monkeypatch):
    database = pg_databases["knowledge"]
    store = KnowledgeStore(database)
    store.initialize()
    rules = json.loads(dataset_path("rules.json").read_text())
    dishes = json.loads(dataset_path("dishes.json").read_text())
    rules["authoring_review"] = {"status": "BLOCKED_FOR_PUBLICATION", "blockers": ["clinical approval pending"]}
    store.create_draft("review-test", rules, dishes, actor="technical-author")
    for key in ("CARELOOP_KNOWLEDGE_DATABASE_URL", "CARELOOP_KNOWLEDGE_DATABASE_URL_FILE", "CARELOOP_KNOWLEDGE_RELEASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CARELOOP_KNOWLEDGE_DATABASE_URL", database)
    monkeypatch.setenv("CARELOOP_REVIEW_DRAFT", "review-test")
    monkeypatch.setenv("CARELOOP_REVIEW_REVISION", "1")
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "review")
    return store, rules, dishes


def test_review_starts_without_publishing_and_pins_documents(review_store):
    store, rules, dishes = review_store
    before = store.history("review-test")
    with TestClient(create_app()) as client:
        health = client.get("/healthz").json()
        assert health["deployment_mode"] == "review"
        assert health["clinical_workflows_enabled"] is False
        response = client.get("/knowledge-review")
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["draft"]["review"] is None
        assert response.json()["draft"]["release_id"] is None
        assert response.json()["technical_review"]["status"] == "BLOCKED_FOR_PUBLICATION"
        assert client.get("/knowledge-review/documents").json()["rules"] == rules
        assert client.get("/knowledge-review/documents").json()["dishes"] == dishes
        store.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="new revision")
        assert client.get("/knowledge-review").json()["draft"]["revision"] == 1
    assert len(store.history("review-test")) == len(before) + 1


@pytest.mark.parametrize("method,path", [
    ("get", "/patients"), ("get", "/plans"), ("post", "/rules/run"),
    ("post", "/envelopes/id/approve"), ("post", "/plans/generate"),
    ("post", "/chat"), ("get", "/kb/stats"), ("get", "/dishes"),
    ("get", "/observations"), ("post", "/knowledge-review"),
    ("delete", "/knowledge-review/documents"), ("post", "/healthz"),
])
def test_review_surface_rejects_clinical_routes_and_all_mutations(review_store, method, path):
    store, _, _ = review_store
    before = store.history("review-test")
    with TestClient(create_review_app()) as client:
        response = getattr(client, method)(path)
        assert response.status_code == 503
        assert response.json()["error"] == "review_only_deployment"
    assert store.history("review-test") == before


def test_api_docs_work_behind_stripped_prefix(review_store):
    with TestClient(create_review_app()) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert "/api/openapi.json" in response.text
        schema = client.get("/openapi.json").json()
        assert schema["servers"] == [{"url": "/api"}]
        assert all("get" in operations for operations in schema["paths"].values())
        assert "/plans" not in schema["paths"]
        assert client.get("/api/knowledge-review").status_code == 200


@pytest.mark.parametrize("key,value", [
    ("CARELOOP_REVIEW_DRAFT", ""), ("CARELOOP_REVIEW_DRAFT", "missing"),
    ("CARELOOP_REVIEW_REVISION", ""), ("CARELOOP_REVIEW_REVISION", "0"),
    ("CARELOOP_REVIEW_REVISION", "not-an-integer"), ("CARELOOP_REVIEW_REVISION", "2"),
    ("CARELOOP_KNOWLEDGE_RELEASE", "some-release"),
])
def test_review_configuration_fails_closed(review_store, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError), TestClient(create_review_app()):
        pass


def test_old_revision_cannot_be_selected_as_current(review_store):
    store, rules, dishes = review_store
    store.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="edit")
    with pytest.raises(ValueError, match="not current"), TestClient(create_review_app()):
        pass


def test_unknown_deployment_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "approve-everything")
    with pytest.raises(ValueError, match="published or review"):
        create_app()


def test_published_mode_keeps_original_application(monkeypatch):
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "published")
    from backend.app.main import app

    assert create_app() is app
