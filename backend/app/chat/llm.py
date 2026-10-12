"""Chat adapter boundary with an offline template implementation.

``build_adapter`` always returns TemplateLLM. Provider/model resolution is
metadata only, not an active hosted or Ollama connection. Future adapters must
preserve the grounding contract; the answer pipeline does not enforce it on
their generated text.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from backend.app.core.llm_choice import choose_llm

__all__ = ["LLMAdapter", "TemplateLLM", "active_adapter_info", "build_adapter"]


@runtime_checkable
class LLMAdapter(Protocol):
    """Adapter expected to preserve facts and citations in already-grounded text."""

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        """Produce a completion for ``prompt`` grounded in ``context``."""
        ...  # pragma: no cover


class TemplateLLM:
    """Deterministic, offline template adapter.

    Returns the prompt followed by supplied context key/value lines. No network
    calls or generated facts are involved.
    """

    name = "template-llm"

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        lines = [str(prompt)]
        if context:
            for key, value in context.items():
                lines.append(f"{key}: {value}")
        return "\n".join(lines)


def build_adapter(
    env: dict[str, str] | None = None,
) -> tuple[LLMAdapter, dict[str, Any]]:
    """Return the active ``(adapter, info)`` pair.

    ``info["resolved"]`` mirrors ``llm_choice.choose_llm`` (documented priority:
    explicit override -> OPENAI_API_KEY -> GOOGLE_API_KEY -> local Ollama);
    ``info["active"]`` names the adapter actually serving completions, which in
    this implementation is always the deterministic template adapter.
    """
    choice = choose_llm(env if env is not None else os.environ)
    return TemplateLLM(), {"resolved": asdict(choice), "active": TemplateLLM.name}


def active_adapter_info(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Metadata only (no adapter construction) for /healthz-style reporting."""
    choice = choose_llm(env if env is not None else os.environ)
    return {"resolved": asdict(choice), "active": TemplateLLM.name}
