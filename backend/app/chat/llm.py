from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from backend.app.core.llm_choice import choose_llm

__all__ = [
    "LLMAdapter",
    "OpenAICompatLLM",
    "TemplateLLM",
    "active_adapter_info",
    "build_adapter",
    "build_openai_compat_adapter",
]


@runtime_checkable
class LLMAdapter(Protocol):
    """Preserve facts and citations from grounded input."""

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        ...  # pragma: no cover


class TemplateLLM:
    name = "template-llm"

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        lines = [prompt]
        if context:
            for key, value in context.items():
                lines.append(f"{key}: {value}")
        return "\n".join(lines)


class OpenAICompatLLM:
    name = "openai-compat-llm"

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        url = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("OpenAI-compatible response missing choices[0]")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise ValueError("OpenAI-compatible response missing string message.content")  # noqa: TRY004
        return content

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        sys_msg = (
            "You are a clinical nutrition assistant. Use only the provided grounded "
            "context and preserve every rule_id/guideline citation verbatim."
        )
        user_content = prompt
        if context:
            user_content = f"{prompt}\n\nContext:\n{json.dumps(context, ensure_ascii=False)}"
        return self.chat_completion(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )


def build_openai_compat_adapter(
    env: dict[str, str] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
) -> OpenAICompatLLM:
    environ = env if env is not None else os.environ
    choice = choose_llm(environ)
    resolved_base = (
        base_url
        or environ.get("CARELOOP_OPENAI_BASE_URL")
        or environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    resolved_key = (
        api_key
        if api_key is not None
        else (environ.get("CARELOOP_OPENAI_API_KEY") or environ.get("OPENAI_API_KEY") or "")
    )
    resolved_model = (
        model
        or environ.get("CARELOOP_LLM_MODEL")
        or environ.get("OPENAI_MODEL")
        or (choice.model if choice.model != "deterministic-template-v1" else "gpt-4o-mini")
    )
    return OpenAICompatLLM(
        base_url=resolved_base,
        api_key=resolved_key,
        model=resolved_model,
        timeout=timeout,
    )


def build_adapter(
    env: dict[str, str] | None = None,
) -> tuple[LLMAdapter, dict[str, Any]]:
    """Resolved provider metadata does not change the active template adapter."""
    choice = choose_llm(env if env is not None else os.environ)
    return TemplateLLM(), {"resolved": asdict(choice), "active": TemplateLLM.name}


def active_adapter_info(env: dict[str, str] | None = None) -> dict[str, Any]:
    choice = choose_llm(env if env is not None else os.environ)
    return {"resolved": asdict(choice), "active": TemplateLLM.name}
