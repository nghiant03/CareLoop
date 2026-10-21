import pytest
from fastapi.testclient import TestClient

from backend.app.review_preview import create_review_app


@pytest.fixture
def writable_review(review_store, monkeypatch, tmp_path):
    store, _, _ = review_store
    secret = tmp_path / "operator_url"
    secret.write_text(store.database)
    monkeypatch.setenv("CARELOOP_REVIEW_OPERATOR_URL_FILE", str(secret))
    return store


def test_review_history_and_revision_are_read_only(review_store):
    store, rules, _ = review_store
    before = store.history("review-test")
    with TestClient(create_review_app()) as client:
        assert client.get("/knowledge-review/history").json() == before
        assert client.get("/knowledge-review/revision?revision=1").json()["rules"] == rules
        assert client.get("/knowledge-review/revision?revision=2").status_code == 404
        assert client.get("/knowledge-review/revision?revision=0").status_code == 404
    assert store.history("review-test") == before


def test_decision_requires_token_and_explicit_operator(review_store):
    with TestClient(create_review_app()) as client:
        status = client.get("/knowledge-review").json()
        payload = {"actor": "independent-reviewer", "decision": "reject", "expected_revision": 1, "note": "Source review incomplete"}
        assert client.post("/knowledge-review/decision", json=payload).status_code == 403
        assert client.post("/knowledge-review/decision", json=payload,
                           headers={"X-Review-Token": status["csrf_token"]}).status_code == 403


def test_review_is_revision_bound_and_never_publishes(writable_review):
    with TestClient(create_review_app()) as client:
        status = client.get("/knowledge-review").json()
        headers = {"X-Review-Token": status["csrf_token"]}
        payload = {"actor": "independent-reviewer", "decision": "reject", "expected_revision": 1, "note": "Clinical exclusions remain unresolved"}
        assert client.post("/knowledge-review/decision", json={**payload, "expected_revision": 2}, headers=headers).status_code == 409
        assert client.post("/knowledge-review/decision", json={**payload, "actor": "technical-author"}, headers=headers).status_code == 409
        response = client.post("/knowledge-review/decision", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["review"]["decision"] == "reject"
        assert response.json()["release_id"] is None
        assert client.post("/knowledge-review/decision", json=payload, headers=headers).status_code == 409
        assert client.post("/knowledge-review/publish", json={}).status_code == 503
        assert client.get("/knowledge-review").json()["current_draft"]["review"]["decision"] == "reject"
    assert writable_review.show("review-test")["release_id"] is None


def test_edit_prevents_review_of_stale_snapshot(writable_review, review_store):
    _, rules, dishes = review_store
    with TestClient(create_review_app()) as client:
        status = client.get("/knowledge-review").json()
        writable_review.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="Correct evidence")
        response = client.post("/knowledge-review/decision", headers={"X-Review-Token": status["csrf_token"]},
                               json={"actor": "reviewer", "decision": "approve", "expected_revision": 1, "note": "Reviewed"})
        assert response.status_code == 409
        assert client.get("/knowledge-review").json()["current_draft"]["revision"] == 2
    assert writable_review.show("review-test")["review"] is None
