"""Resolve LLM and embedding configuration without constructing clients.

Configured defaults
-------------------
Embeddings
    - default: ``nomic-embed-text`` served by a local **Ollama** instance.
    - override: set ``CARE_LOOP_LLM_BACKEND=local_st`` to use
      ``sentence-transformers/all-MiniLM-L6-v2`` (no Ollama required).

Chat LLM
    - default (no API keys): ``llama3.2:3b`` via local **Ollama**.
    - if ``OPENAI_API_KEY`` is set: ``gpt-4o-mini`` (OpenAI).
    - if ``GOOGLE_API_KEY`` is set: ``gemini-2.0-flash`` (Google).

Resolution priority (first match wins)
--------------------------------------
1. ``CARE_LOOP_LLM_BACKEND=openai|google|ollama`` selects that chat provider.
2. With no backend override, ``OPENAI_API_KEY`` selects OpenAI, then
   ``GOOGLE_API_KEY`` selects Google.
3. Otherwise resolve Ollama. Unrecognised backend names also use this fallback.
``CARE_LOOP_LLM_MODEL`` overrides the chosen provider's model, not its provider.
Embedding resolution is independent of API-key detection.

These are resolved choices, not evidence that a provider serves traffic.
The active chat adapter is selected separately in ``chat/llm.py``.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Literal, Mapping

__all__ = [
    "EmbeddingChoice",
    "LLMChoice",
    "choose_embedding",
    "choose_llm",
    "describe_choices",
]

Provider = Literal["ollama", "openai", "google", "local_st"]


def _effective_env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


@dataclass(frozen=True)
class EmbeddingChoice:
    provider: str
    model: str
    requires_api_key: bool
    reason: str


@dataclass(frozen=True)
class LLMChoice:
    provider: str
    model: str
    requires_api_key: bool
    base_url: str | None
    reason: str


def choose_embedding(env: Mapping[str, str] | None = None) -> EmbeddingChoice:
    """Resolve local_st for backend aliases local_st/st/sentence-transformers.

    Otherwise resolve Ollama with CARE_LOOP_EMBED_MODEL or nomic-embed-text.
    No client is constructed and provider availability is not checked.
    """
    config = _effective_env(env)
    backend = config.get("CARE_LOOP_LLM_BACKEND", "").strip().lower()
    if backend in {"local_st", "sentence-transformers", "st"}:
        return EmbeddingChoice(
            provider="local_st",
            model="sentence-transformers/all-MiniLM-L6-v2",
            requires_api_key=False,
            reason="CARE_LOOP_LLM_BACKEND=local_st override",
        )
    return EmbeddingChoice(
        provider="ollama",
        model=config.get("CARE_LOOP_EMBED_MODEL", "nomic-embed-text"),
        requires_api_key=False,
        reason="default local Ollama embedding model",
    )


def choose_llm(env: Mapping[str, str] | None = None) -> LLMChoice:
    """Resolve the chat LLM per the documented priority."""
    config = _effective_env(env)
    backend = config.get("CARE_LOOP_LLM_BACKEND", "").strip().lower()
    override_model = config.get("CARE_LOOP_LLM_MODEL", "").strip()

    if backend == "openai" or (backend == "" and config.get("OPENAI_API_KEY")):
        return LLMChoice(
            provider="openai",
            model=override_model or "gpt-4o-mini",
            requires_api_key=True,
            base_url=config.get("OPENAI_BASE_URL"),
            reason="OPENAI_API_KEY set (or explicit override)",
        )
    if backend == "google" or (backend == "" and config.get("GOOGLE_API_KEY")):
        return LLMChoice(
            provider="google",
            model=override_model or "gemini-2.0-flash",
            requires_api_key=True,
            base_url=None,
            reason="GOOGLE_API_KEY set (or explicit override)",
        )
    if backend == "ollama":
        return LLMChoice(
            provider="ollama",
            model=override_model or "llama3.2:3b",
            requires_api_key=False,
            base_url=config.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            reason="CARE_LOOP_LLM_BACKEND=ollama override",
        )
    return LLMChoice(
        provider="ollama",
        model=override_model or "llama3.2:3b",
        requires_api_key=False,
        base_url=config.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        reason="default: local Ollama, no API key required",
    )


def describe_choices(env: Mapping[str, str] | None = None) -> dict[str, dict]:
    """Return both resolved choices as plain dicts (useful for /healthz/debug)."""
    return {
        "embedding": asdict(choose_embedding(env)),
        "llm": asdict(choose_llm(env)),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(describe_choices(), indent=2))
