from uuid import uuid4

from test_inference import extracted, response

from careloop.inference import InferenceError, Settings, configured_client

REVIEWER = {"actor": {"name": "Test reviewer", "role": "reviewer"}, "reason": "Test extraction"}


class Provider:
    settings = Settings("https://test.example/v1/", "test-key")

    def __init__(self, content=None, error=None):
        self.content = content or extracted()
        self.error = error
        self.calls = 0
        self.during_call = None

    def complete(self, *args, **kwargs):
        self.last_request = kwargs
        self.calls += 1
        if self.during_call:
            self.during_call()
        if self.error:
            raise InferenceError(self.error)
        return response(self.content)


def setup(client, provider):
    client.app.dependency_overrides[configured_client] = lambda: provider
    source = client.post(
        "/api/evidence/sources",
        json={
            **REVIEWER,
            "title": "Test",
            "locator": "Test",
            "edition": "Test",
            "content": "Test passage",
        },
    ).json()
    return f"/api/evidence/sources/{source['id']}/extractions"


def test_extraction_saves_review_blocked_drafts_and_reuses_request_id(client):
    provider = Provider()
    path = setup(client, provider)
    data = {**REVIEWER, "request_id": str(uuid4()), "passage_ordinal": 1}
    first = client.post(path, json=data)
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["state"] == "completed" and len(run["rule_ids"]) == 1
    assert "test-key" not in first.text
    rule = client.get(f"/api/evidence/rules/{run['rule_ids'][0]}").json()
    assert rule["active_revision"] is None
    assert rule["revisions"][0]["body"]["blockers"]
    assert rule["revisions"][0]["body"]["quote"] == "Test passage"
    assert run["request"]["response_format"]["json_schema"]["strict"] is True
    assert run["request"]["response_format"] == provider.last_request["response_format"]
    assert provider.last_request["model"] == "glm-5.3"
    assert run["request"]["model"] == "glm-5.3"
    approval = client.post(
        "/api/evidence/approvals",
        json={
            **REVIEWER,
            "rules": [{"rule_id": rule["id"], "revision": 1}],
        },
    )
    assert approval.status_code == 409
    assert client.post(path, json=data).json() == run
    assert client.post(path, json={**data, "model": "glm-5.3"}).json() == run
    assert provider.calls == 1
    assert (
        client.post(path, json={**data, "generation": {"reasoning_effort": "high"}}).status_code
        == 409
    )
    assert client.get(path + "/" + data["request_id"]).json() == run
    history = client.get(path + "?limit=1").json()
    assert history[0]["id"] == data["request_id"]
    assert history[0]["rule_ids"] == run["rule_ids"]
    assert "response" not in history[0]
    assert client.post(path, json={**data, "model": "other"}).status_code == 409
    assert provider.calls == 1


def test_invalid_extraction_retains_response_without_creating_drafts(client):
    invalid = extracted()
    invalid["rules"][0]["applicability"] = [{"fact": "ckd_stage", "operator": "gte", "value": 3}]
    provider = Provider(invalid)
    path = setup(client, provider)
    data = {**REVIEWER, "request_id": str(uuid4()), "passage_ordinal": 1, "model": "test"}
    run = client.post(path, json=data).json()
    assert run["state"] == "failed" and not run["rule_ids"]
    assert run["response"] and "predicate" in run["error"]
    client.post(path, json=data)
    assert provider.calls == 1


def test_pending_run_is_visible_and_duplicate_does_not_call_provider(client):
    provider = Provider()
    path = setup(client, provider)
    data = {**REVIEWER, "request_id": str(uuid4()), "passage_ordinal": 1, "model": "test"}

    def repeat_request():
        duplicate = client.post(path, json=data)
        assert duplicate.status_code == 201
        assert duplicate.json()["state"] == "pending"

    provider.during_call = repeat_request
    assert client.post(path, json=data).json()["state"] == "completed"
    assert provider.calls == 1


def test_provider_failure_is_recorded_and_role_guard_prevents_calls(client):
    provider = Provider(error="Provider returned HTTP 429")
    path = setup(client, provider)
    data = {**REVIEWER, "request_id": str(uuid4()), "passage_ordinal": 1, "model": "test"}
    forbidden = client.post(path, json={**data, "actor": {"name": "Patient", "role": "patient"}})
    assert forbidden.status_code == 403 and provider.calls == 0
    run = client.post(path, json=data).json()
    assert run["state"] == "failed" and run["response"] is None
    client.post(path, json=data)
    assert provider.calls == 1
