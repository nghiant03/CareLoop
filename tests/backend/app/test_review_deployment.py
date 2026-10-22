"""Operator deployment bootstraps without a release and never serves clinical routes."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.deployment import create_app
from backend.app.review_preview import create_review_app
from backend.datasets.paths import dataset_path
from backend.knowledge.store import KnowledgeStore


@pytest.fixture
def review_store(pg_databases, monkeypatch):
    store = KnowledgeStore(pg_databases["knowledge"])
    store.initialize()
    rules = json.loads(dataset_path("rules.json").read_text())
    dishes = json.loads(dataset_path("dishes.json").read_text())
    rules["authoring_review"] = {"status": "BLOCKED_FOR_PUBLICATION", "blockers": ["clinical approval pending"]}
    store.create_draft("review-test", rules, dishes, actor="technical-author")
    monkeypatch.setenv("CARELOOP_KNOWLEDGE_DATABASE_URL", store.database)
    monkeypatch.delenv("CARELOOP_KNOWLEDGE_RELEASE", raising=False)
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "review")
    return store, rules, dishes


def test_workspace_lists_drafts_without_publishing(review_store):
    store, rules, dishes = review_store
    before = store.history("review-test")
    with TestClient(create_app()) as client:
        assert client.get("/healthz").json()["clinical_workflows_enabled"] is False
        response = client.get("/knowledge")
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["drafts"][0]["review"] is None
        assert response.json()["discovery_available"] is False
        snapshot = client.get("/knowledge/drafts/review-test").json()
        assert snapshot["documents"] == {"rules": rules, "dishes": dishes}
        assert snapshot["events"] == before
        store.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="new revision")
        assert client.get("/knowledge/drafts/review-test").json()["revision"] == 2
        assert client.get("/knowledge/drafts/review-test?revision=1").json()["revision"] == 1
    assert len(store.history("review-test")) == len(before) + 1


@pytest.mark.parametrize("method,path", [
    ("get", "/patients"), ("get", "/plans"), ("post", "/rules/run"),
    ("post", "/envelopes/id/approve"), ("post", "/plans/generate"),
    ("post", "/chat"), ("get", "/kb/stats"), ("get", "/dishes"),
    ("get", "/observations"),
])
def test_workspace_rejects_clinical_routes(review_store, method, path):
    store, _, _ = review_store
    before = store.history("review-test")
    with TestClient(create_review_app()) as client:
        response = getattr(client, method)(path)
        assert response.status_code == 503
        assert response.json()["error"] == "review_only_deployment"
    assert store.history("review-test") == before


def test_api_docs_work_behind_stripped_prefix(review_store):
    with TestClient(create_review_app()) as client:
        assert "/api/openapi.json" in client.get("/docs").text
        schema = client.get("/openapi.json").json()
        assert schema["servers"] == [{"url": "/api"}]
        assert "/knowledge/drafts" in schema["paths"]
        assert "/plans" not in schema["paths"]
        assert client.get("/api/knowledge").status_code == 200


def test_selected_live_release_is_refused(review_store, monkeypatch):
    monkeypatch.setenv("CARELOOP_KNOWLEDGE_RELEASE", "some-release")
    with pytest.raises(ValueError, match="live release"), TestClient(create_review_app()):
        pass


def test_missing_database_is_refused(review_store, monkeypatch):
    monkeypatch.delenv("CARELOOP_KNOWLEDGE_DATABASE_URL")
    with pytest.raises(ValueError, match="PostgreSQL URL"), TestClient(create_review_app()):
        pass


def test_unknown_deployment_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "approve-everything")
    with pytest.raises(ValueError, match="published or review"):
        create_app()


def test_published_mode_keeps_original_application(monkeypatch):
    monkeypatch.setenv("CARELOOP_DEPLOYMENT_MODE", "published")
    from backend.app.main import app
    assert create_app() is app
