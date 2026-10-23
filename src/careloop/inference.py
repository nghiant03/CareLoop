import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import httpx
from dotenv import dotenv_values
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MODEL = "glm-5.3"


class InferenceError(Exception):
    def __init__(self, message, *, stage="transport"):
        super().__init__(message)
        self.stage = stage


class CompletionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    response_mode: Literal["json_schema", "json_object"] = "json_schema"
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = (
        None
    )
    max_tokens: Annotated[int, Field(ge=1, le=8192)] = 4096
    temperature: Annotated[float, Field(ge=0, le=2)] | None = 0


def strict_schema(output_model):
    schema = deepcopy(output_model.model_json_schema())

    def visit(node):
        node.pop("default", None)
        if "const" in node:
            node["enum"] = [node.pop("const")]
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
        for mapping in ("properties", "$defs"):
            for child in node.get(mapping, {}).values():
                visit(child)
        for keyword in ("anyOf", "allOf", "oneOf"):
            for child in node.get(keyword, []):
                visit(child)
        if isinstance(node.get("items"), dict):
            visit(node["items"])

    visit(schema)
    return schema


def completion_request(model, messages, output_model, options=None):
    options = options or CompletionOptions()
    output_format = {"type": options.response_mode}
    if options.response_mode == "json_schema":
        output_format["json_schema"] = {
            "name": output_model.__name__,
            "strict": True,
            "schema": strict_schema(output_model),
        }
    return {
        "model": DEFAULT_MODEL if model is None else model,
        "messages": messages,
        "max_tokens": options.max_tokens,
        "temperature": options.temperature,
        "response_format": output_format,
        "reasoning_effort": options.reasoning_effort,
    }


def configured_client():
    with InferenceClient(Settings.load()) as client:
        yield client


@dataclass(frozen=True)
class Settings:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)

    @classmethod
    def load(cls, env_file=Path(".env")):
        values = {**dotenv_values(env_file, interpolate=False), **os.environ}
        base = (values.get("LLM_BASE_URL") or "").strip()
        key = (values.get("LLM_API_KEY") or "").strip()
        if not base or not key:
            raise InferenceError("Set LLM_BASE_URL and LLM_API_KEY in the environment or .env")
        try:
            url = httpx.URL(base)
        except httpx.InvalidURL:
            raise InferenceError("LLM_BASE_URL is not a valid URL") from None
        local = url.host in {"localhost", "127.0.0.1", "::1"}
        if (
            not url.host
            or (url.scheme != "https" and not (url.scheme == "http" and local))
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise InferenceError(
                "Use an HTTPS API base URL without credentials, query, or fragment"
            )
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise InferenceError("LLM_API_KEY contains invalid header characters")
        return cls(str(url).rstrip("/") + "/", key)


class InferenceClient:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=httpx.Timeout(120, connect=10),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def request(self, method, path, payload=None):
        try:
            with self.client.stream(method, path, json=payload) as response:
                if not response.is_success:
                    raise InferenceError(f"Provider returned HTTP {response.status_code}")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise InferenceError("Provider response exceeds 2 MB")
            result = json.loads(content)
        except (httpx.HTTPError, ValueError) as exc:
            # Provider bodies and exception URLs can echo credentials.
            raise InferenceError(f"Provider request failed ({type(exc).__name__})") from None
        if not isinstance(result, dict):
            raise InferenceError("Provider response must be a JSON object")
        return result

    def models(self):
        result = self.request("GET", "models")
        data = result.get("data")
        if not isinstance(data, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in data
        ):
            raise InferenceError("Provider models response must contain data with model IDs")
        return sorted({item["id"] for item in data})

    def complete(
        self,
        model,
        messages,
        max_tokens=512,
        *,
        response_format=None,
        reasoning_effort=None,
        temperature=0,
    ):
        if not model or not 1 <= max_tokens <= 8192:
            raise InferenceError("Specify a model and an output limit between 1 and 8192 tokens")
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False}
        for name, value in (
            ("response_format", response_format),
            ("reasoning_effort", reasoning_effort),
            ("temperature", temperature),
        ):
            if value is not None:
                payload[name] = value
        return self.request(
            "POST",
            "chat/completions",
            payload,
        )


def completion_text(response):
    try:
        choice = response["choices"][0]
        if choice["message"].get("refusal"):
            raise InferenceError("Provider refused the request", stage="refusal")
        if choice.get("finish_reason") == "length":
            raise InferenceError("Provider exhausted the output token budget", stage="truncation")
        text = choice["message"]["content"]
        if choice.get("finish_reason") != "stop" or not isinstance(text, str) or not text.strip():
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise InferenceError(
            "Provider returned no complete text answer", stage="response"
        ) from None
    return text


def parse_output(response, output_model):
    try:
        content = json.loads(completion_text(response))
    except json.JSONDecodeError:
        raise InferenceError("Provider output is not a JSON document", stage="json") from None
    try:
        Draft202012Validator(strict_schema(output_model)).validate(content)
        return output_model.model_validate(content, strict=True)
    except (ValidationError, SchemaValidationError):
        raise InferenceError("Provider output does not match the schema", stage="schema") from None
