from fastapi.testclient import TestClient

from backend.app.review_preview import create_review_app
from tests.backend.app.test_review_deployment import review_store  # noqa: F401


def test_history_and_revision_reads_do_not_write(review_store):
    store, rules, _ = review_store
    before = store.history("review-test")
    with TestClient(create_review_app()) as client:
        snapshot = client.get("/knowledge/drafts/review-test?revision=1").json()
        assert snapshot["events"] == before
        assert snapshot["documents"]["rules"] == rules
        for revision in (0, 2):
            assert client.get(f"/knowledge/drafts/review-test?revision={revision}").status_code == 404
    assert store.history("review-test") == before


def test_review_is_independent_revision_bound_and_never_activates(review_store):
    store, _, _ = review_store
    with TestClient(create_review_app()) as client:
        headers = {"X-Review-Token": client.get("/knowledge").json()["csrf_token"]}
        payload = {"actor": "reviewer", "decision": "reject", "expected_revision": 1, "note": "Evidence incomplete", "confirmed": True}
        path = "/knowledge/drafts/review-test/review"
        assert client.post(path, json=payload).status_code == 403
        assert client.post(path, json={**payload, "confirmed": False}, headers=headers).status_code == 422
        assert client.post(path, json={**payload, "expected_revision": 2}, headers=headers).status_code == 409
        assert client.post(path, json={**payload, "actor": "technical-author"}, headers=headers).status_code == 409
        assert client.post(path, json=payload, headers=headers).json()["review"]["decision"] == "reject"
        assert client.post(path, json=payload, headers=headers).status_code == 409
    assert store.show("review-test")["release_id"] is None


def test_browser_create_edit_review_publish_export_clone_workflow(review_store):
    store, rules, dishes = review_store
    with TestClient(create_review_app()) as client:
        headers = {"X-Review-Token": client.get("/knowledge").json()["csrf_token"]}
        created = client.post("/knowledge/drafts", headers=headers,
                              json={"draft_id": "new", "actor": "author", "rules": rules, "dishes": dishes})
        assert created.status_code == 201
        assert created.json()["revision"] == 1
        edit = {"actor": "editor", "note": "Reviewed changes", "expected_revision": 1, "rules": rules, "dishes": dishes}
        assert client.put("/knowledge/drafts/new", headers=headers, json=edit).json()["revision"] == 2
        assert client.put("/knowledge/drafts/new", headers=headers, json=edit).status_code == 409
        publish = {"actor": "publisher", "note": "Freeze reviewed revision", "expected_revision": 2, "release_id": "release-1", "confirmed": True}
        assert client.post("/knowledge/drafts/new/publish", headers=headers, json=publish).status_code == 409
        review = {"actor": "reviewer", "note": "Independent review", "expected_revision": 2, "decision": "approve", "confirmed": True}
        assert client.post("/knowledge/drafts/new/review", headers=headers, json=review).status_code == 200
        published = client.post("/knowledge/drafts/new/publish", headers=headers, json=publish)
        assert published.status_code == 200
        assert published.json()["activated"] is False
        exported = client.get("/knowledge/releases/release-1").json()
        assert exported["rules"] == rules and exported["dishes"] == dishes
        assert client.put("/knowledge/drafts/new", headers=headers, json={**edit, "expected_revision": 2}).status_code == 409
        cloned = client.post("/knowledge/clone", headers=headers,
                             json={"release_id": "release-1", "draft_id": "next", "actor": "author"})
        assert cloned.status_code == 201
        assert cloned.json()["parent_release"] == "release-1"
        assert cloned.json()["review"] is None
        assert len(client.get("/knowledge/drafts/new").json()["events"]) == 4


def test_edit_prevents_stale_review(review_store):
    store, rules, dishes = review_store
    with TestClient(create_review_app()) as client:
        headers = {"X-Review-Token": client.get("/knowledge").json()["csrf_token"]}
        store.edit_draft("review-test", rules, dishes, actor="editor", expected_revision=1, note="Correct evidence")
        response = client.post("/knowledge/drafts/review-test/review", headers=headers,
                               json={"actor": "reviewer", "decision": "approve", "expected_revision": 1, "note": "Reviewed", "confirmed": True})
        assert response.status_code == 409
    assert store.show("review-test")["review"] is None
