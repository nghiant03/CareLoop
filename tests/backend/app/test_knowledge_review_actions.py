from fastapi.testclient import TestClient

from backend.app.review_preview import create_review_app


def test_review_history_and_revision_are_read_only(review_store):
    store, rules, _ = review_store
    before = store.history("review-test")
    with TestClient(create_review_app()) as client:
        assert client.get("/knowledge-review/history").json() == before
        assert client.get("/knowledge-review/revision?revision=1").json()["rules"] == rules
        assert client.get("/knowledge-review/revision?revision=2").status_code == 404
        assert client.get("/knowledge-review/revision?revision=0").status_code == 404
    assert store.history("review-test") == before


def test_decision_requires_token(review_store):
    with TestClient(create_review_app()) as client:
        payload = {"actor": "independent-reviewer", "decision": "reject", "expected_revision": 1, "note": "Source review incomplete"}
        assert client.post("/knowledge-review/decision", json=payload).status_code == 403


def test_review_is_revision_bound_and_never_publishes(review_store):
    store, _, _ = review_store
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
    assert store.show("review-test")["release_id"] is None


def test_edit_prevents_review_of_stale_snapshot(review_store):
    store, rules, dishes = review_store
    with TestClient(create_review_app()) as client:
        status = client.get("/knowledge-review").json()
        store.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="Correct evidence")
        response = client.post("/knowledge-review/decision", headers={"X-Review-Token": status["csrf_token"]},
                               json={"actor": "reviewer", "decision": "approve", "expected_revision": 1, "note": "Reviewed"})
        assert response.status_code == 409
        assert client.get("/knowledge-review").json()["current_draft"]["revision"] == 2
    assert store.show("review-test")["review"] is None
