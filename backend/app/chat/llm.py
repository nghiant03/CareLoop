"""LLM adapter boundary for the chat pipeline.

Per ``backend/app/core/llm_choice.py`` the documented default chat model is a
local Ollama model (``llama3.2:3b``) with optional OpenAI/Google overrides.
Week 1 ships a **deterministic template adapter** (:class:`TemplateLLM`) as
the active implementation — the prototype must never fabricate content, and
deterministic template assembly makes the grounded-answer contract testable.

A real API-backed adapter can be plugged in later by implementing
:class:`LLMAdapter` and registering it in :func:`build_adapter`; the resolved
provider/model from ``llm_choice.py`` is surfaced in the adapter metadata so
wiring code can report which backend *would* serve traffic.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Optional, Protocol, runtime_checkable

from backend.app.core.llm_choice import choose_llm

__all__ = ["LLMAdapter", "TemplateLLM", "build_adapter", "active_adapter_info"]


@runtime_checkable
class LLMAdapter(Protocol):
    """Any object with ``generate(prompt, context) -> str``."""

    def generate(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        """Produce a completion for ``prompt`` grounded in ``context``."""
        ...  # pragma: no cover


class TemplateLLM:
    """Deterministic, offline template adapter.

    Assembles a completion purely from the prompt plus the supplied context
    key/value facts — no generation, no network, fully reproducible. Serves as
    the default adapter and as the reference output shape for future
    API-backed adapters.
    """

    name = "template-llm"

    def generate(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        lines = [str(prompt)]
        if context:
            for key, value in context.items():
                lines.append(f"{key}: {value}")
        return "\n".join(lines)


def build_adapter(
    env: Optional[dict[str, str]] = None,
) -> tuple[LLMAdapter, dict[str, Any]]:
    """Return the active ``(adapter, info)`` pair.

    ``info["resolved"]`` mirrors ``llm_choice.choose_llm`` (documented priority:
    explicit override -> OPENAI_API_KEY -> GOOGLE_API_KEY -> local Ollama);
    ``info["active"]`` names the adapter actually serving completions, which in
    Week 1 is always the deterministic template adapter.
    """
    choice = choose_llm(env if env is not None else os.environ)
    return TemplateLLM(), {"resolved": asdict(choice), "active": TemplateLLM.name}


def active_adapter_info(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Metadata only (no adapter construction) for /healthz-style reporting."""
    choice = choose_llm(env if env is not None else os.environ)
    return {"resolved": asdict(choice), "active": TemplateLLM.name}