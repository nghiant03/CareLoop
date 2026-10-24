import json
from typing import Literal

import httpx
import pytest
from jsonschema import Draft202012Validator

from careloop import answers
from careloop.evidence import extraction
from careloop.evidence.models import Model
from careloop.inference import (
    CompletionOptions,
    InferenceClient,
    InferenceError,
    Settings,
    completion_text,
    strict_schema,
)


def response(content, finish="stop"):
    return {"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": finish}]}


def extracted():
    return {
        "rules": [
            {
                "applicability": [],
                "population_note": "Test population",
                "exceptions": [],
                "exception_note": "None stated",
                "action": {
                    "kind": "ceiling",
                    "subject": "sodium",
                    "amount": 100,
                    "upper": None,
                    "unit": "mg/day",
                    "advice": "Test recommendation",
                    "upper_exclusive": False,
                },
                "blockers": [],
            }
        ],
        "limitations": [],
    }


def test_configuration_precedence_and_secret_handling(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LLM_BASE_URL=https://test.example/prefix/v1\nLLM_API_KEY='literal${KEY}'\n")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = Settings.load(env)
    assert settings.base_url == "https://test.example/prefix/v1/"
    assert settings.api_key == "literal${KEY}"
    assert "literal" not in repr(settings) and "test.example" not in repr(settings)
    monkeypatch.setenv("LLM_API_KEY", "override")
    assert Settings.load(env).api_key == "override"
    monkeypatch.setenv("LLM_BASE_URL", "https://user:secret@test.example/v1")
    with pytest.raises(InferenceError) as exc:
        Settings.load(env)
    assert "secret" not in str(exc.value)


def test_client_preserves_prefix_and_never_retries_or_follows_redirects():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}]})
        return httpx.Response(307, headers={"location": "https://other.example/"})

    with InferenceClient(
        Settings("https://test.example/prefix/v1/", "secret"),
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.models() == ["model-a", "model-b"]
        with pytest.raises(InferenceError, match="HTTP 307"):
            client.complete("model-a", [{"role": "user", "content": "Test"}], 10)
    assert [r.url.path for r in seen] == ["/prefix/v1/models", "/prefix/v1/chat/completions"]
    assert json.loads(seen[1].content)["max_tokens"] == 10


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_do_not_echo_credentials(status):
    with InferenceClient(
        Settings("https://test.example/v1/", "secret"),
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="secret")),
    ) as client:
        with pytest.raises(InferenceError) as exc:
            client.models()
    assert "secret" not in str(exc.value)


def test_truncation_refusal_and_domain_errors_are_distinguished():
    with pytest.raises(InferenceError) as exc:
        completion_text(response({}, "length"))
    assert exc.value.stage == "truncation"
    with pytest.raises(InferenceError) as exc:
        completion_text({"choices": [{"message": {"refusal": "No"}}]})
    assert exc.value.stage == "refusal"
    invalid = extracted()
    invalid["rules"][0]["applicability"] = [{"fact": "ckd_stage", "operator": "gte", "value": 3}]
    with pytest.raises(InferenceError) as exc:
        extraction.parse(response(invalid), {"content": "Test passage"})
    assert exc.value.stage == "domain"
    parsed = extraction.parse(response(extracted()), {"content": "Test passage"})
    assert parsed.rules[0].action.amount == 100


def test_citations_must_reference_supplied_text_and_uncertainty_is_explicit():
    answer = {
        "answer": "Test",
        "source_ids": [],
        "needs_clinician": False,
        "insufficient_evidence": False,
    }
    with pytest.raises(InferenceError, match="require source citations"):
        answers.parse(response(answer), [])
    answer["insufficient_evidence"] = True
    assert answers.parse(response(answer), []).insufficient_evidence
    answer["source_ids"] = ["missing"]
    with pytest.raises(InferenceError, match="supplied source"):
        answers.parse(response(answer), [{"id": "source", "text": "Test"}])
    answer["insufficient_evidence"] = False
    answer["source_ids"] = ["source"]
    text = "Exact\nsource \u2013 with whitespace."
    parsed = answers.parse(response(answer), [{"id": "source", "text": text}])
    assert parsed.citations[0].quote == text
    answer["source_ids"] = ["source", "source"]
    with pytest.raises(InferenceError):
        answers.parse(response(answer), [{"id": "source", "text": text}])


def test_strict_schema_requires_nullable_fields_and_rejects_unknown_properties():
    schema = strict_schema(extraction.Extraction)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    valid = extracted()
    validator.validate(valid)
    action_schema = schema["$defs"]["Action"]
    assert set(action_schema["required"]) == set(action_schema["properties"])
    assert action_schema["additionalProperties"] is False
    assert action_schema["properties"]["upper"]["anyOf"][-1] == {"type": "null"}
    del valid["rules"][0]["action"]["upper"]
    assert not validator.is_valid(valid)
    with pytest.raises(InferenceError) as exc:
        extraction.parse(response(valid), {"content": "Test passage"})
    assert exc.value.stage == "schema"
    valid = extracted()
    valid["rules"][0]["action"]["invented"] = 12
    assert not validator.is_valid(valid)


def test_single_literal_uses_portable_enum_in_strict_schema():
    class Probe(Model):
        marker: Literal["schema-bound"]

    schema = strict_schema(Probe)
    assert schema["properties"]["marker"]["enum"] == ["schema-bound"]
    assert "const" not in schema["properties"]["marker"]
    assert not Draft202012Validator(schema).is_valid({"marker": "wrong", "unexpected": True})


@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_structured_output_and_reasoning_are_sent_without_fallback(mode):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, text="unsupported schema, secret")

    payload = extraction.request(
        "test-model",
        {"location": "Test", "content": "Test passage"},
        CompletionOptions(
            response_mode=mode, reasoning_effort="high", max_tokens=4096, temperature=None
        ),
    )
    with InferenceClient(
        Settings("https://test.example/v1/", "secret"), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(InferenceError, match="HTTP 400"):
            client.complete(**payload)
    assert len(seen) == 1
    assert seen[0]["reasoning_effort"] == "high"
    assert seen[0]["max_tokens"] == 4096 and "temperature" not in seen[0]
    assert seen[0]["response_format"]["type"] == mode
    if mode == "json_schema":
        assert seen[0]["response_format"]["json_schema"]["strict"] is True
    else:
        assert seen[0]["response_format"] == {"type": "json_object"}


def test_json_schema_and_domain_validation_are_separate():
    fenced = response({})
    fenced["choices"][0]["message"]["content"] = "```json\n{}\n```"
    with pytest.raises(InferenceError) as exc:
        extraction.parse(fenced, {"content": "Test"})
    assert exc.value.stage == "json"
    with pytest.raises(InferenceError) as exc:
        extraction.parse(response({"rules": "invalid"}), {"content": "Test"})
    assert exc.value.stage == "schema"


def test_answer_flags_do_not_coerce_strings_into_booleans():
    with pytest.raises(InferenceError) as exc:
        answers.parse(
            response(
                {
                    "answer": "Test",
                    "source_ids": [],
                    "needs_clinician": "false",
                    "insufficient_evidence": True,
                }
            ),
            [],
        )
    assert exc.value.stage == "schema"


def test_oversized_and_malformed_provider_responses(monkeypatch):
    monkeypatch.setattr("careloop.inference.MAX_RESPONSE_BYTES", 30)
    with InferenceClient(
        Settings("https://test.example/v1/", "secret"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 31)),
    ) as client:
        with pytest.raises(InferenceError, match="exceeds"):
            client.models()
    with InferenceClient(
        Settings("https://test.example/v1/", "secret"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=["invalid"])),
    ) as client:
        with pytest.raises(InferenceError, match="JSON object"):
            client.models()
