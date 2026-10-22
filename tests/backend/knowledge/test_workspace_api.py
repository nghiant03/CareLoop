import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import review_preview


@pytest.fixture
def workspace(monkeypatch):
    store = SimpleNamespace(initialize=lambda: None, list_drafts=list)
    monkeypatch.setattr(review_preview, "KnowledgeStore", lambda url: store)
    monkeypatch.setattr(review_preview, "database_url", lambda component: "postgresql://test.invalid/never-connected")
    monkeypatch.delenv("CARELOOP_KNOWLEDGE_RELEASE", raising=False)
    return review_preview.create_review_app()


def test_empty_workspace_requires_no_draft_release_or_provider(workspace):
    with TestClient(workspace) as client:
        response = client.get("/knowledge")
        assert response.status_code == 200
        body = response.json()
        assert body["drafts"] == []
        assert body["discovery_available"] is False
        assert body["instructions"]
        assert "api_key" not in body
        headers = {"X-Review-Token": body["csrf_token"]}
        response = client.post("/knowledge/discover", headers=headers,
                               json={"sources": [{"name": "any-guideline.txt", "content": "Some source text"}]})
        assert response.status_code == 503
        assert "No provider has been selected" in response.json()["detail"]


@pytest.mark.parametrize("method,path", [("post", "/knowledge/drafts"), ("put", "/knowledge/drafts/test"),
    ("post", "/knowledge/drafts/test/review"), ("post", "/knowledge/drafts/test/publish"),
    ("post", "/knowledge/clone"), ("post", "/knowledge/discover")])
def test_every_mutation_requires_request_token(workspace, method, path):
    with TestClient(workspace) as client:
        assert getattr(client, method)(path, json={}).status_code == 403


def test_cross_origin_mutations_and_untrusted_hosts_are_rejected(workspace):
    with TestClient(workspace) as client:
        token = client.get("/knowledge").json()["csrf_token"]
        headers = {"X-Review-Token": token, "Origin": "https://untrusted.example"}
        assert client.post("/knowledge/discover", headers=headers, json={}).status_code == 403
        assert client.get("/knowledge", headers={"Host": "untrusted.example"}).status_code == 400


def test_uploads_and_external_instructions_use_provider_neutral_boundary(workspace):
    calls = []

    def extract_candidates(*, instructions, source_text):
        calls.append((instructions, source_text))
        return {"candidates": [{"nutrient": "fiber_g", "kind": "TARGET", "value": 28,
                                "basis": "g_per_day", "quote": source_text}]}

    with TestClient(workspace) as client:
        workspace.state.discovery_client = SimpleNamespace(extract_candidates=extract_candidates)
        headers = {"X-Review-Token": client.get("/knowledge").json()["csrf_token"]}
        passage = "Adults should aim for 28 g of fibre daily."
        payload = {"instructions": "Custom discovery instructions", "sources": [
            {"name": "society-a.md", "content": passage},
            {"name": "society-b.txt", "content": base64.b64encode(passage.encode()).decode(), "encoding": "base64"},
        ]}
        response = client.post("/knowledge/discover", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        report = response.json()
        assert len(report["candidates"]) == 2
        assert [source["path"] for source in report["sources"]] == ["society-a.md", "society-b.txt"]
        assert all(candidate["automatic_activation_allowed"] is False for candidate in report["candidates"])
        assert calls == [(payload["instructions"], passage)] * 2
        assert "sha256" not in response.text
        assert "careloop-discovery-" not in response.text


@pytest.mark.parametrize("name,content,encoding", [("../outside.txt", "source", "text"),
    ("..", "source", "text"), ("unreadable.txt", "!!!not-base64", "base64"), ("source.zip", "not a guideline", "text")])
def test_bad_uploads_fail_without_changing_knowledge(workspace, name, content, encoding):
    with TestClient(workspace) as client:
        workspace.state.discovery_client = SimpleNamespace(extract_candidates=lambda **kwargs: {"candidates": []})
        token = client.get("/knowledge").json()["csrf_token"]
        response = client.post("/knowledge/discover", headers={"X-Review-Token": token},
                               json={"sources": [{"name": name, "content": content, "encoding": encoding}]})
        assert response.status_code == 422


def test_oversize_body_is_rejected_before_validation(workspace, monkeypatch):
    monkeypatch.setattr(review_preview, "MAX_REQUEST_BYTES", 10)
    with TestClient(workspace) as client:
        response = client.post("/knowledge/discover", content=b"x" * 11)
        assert response.status_code == 413
