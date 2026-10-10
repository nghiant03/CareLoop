"""Retrieval-grounded chat pipeline.

Public surface used by the chat API:

* :func:`backend.app.chat.answers.answer` — grounded Q&A with mandatory
  citations, refusal on low confidence and escalation filtering.
* :func:`backend.app.chat.escalation.check` — out-of-scope request filter.
* :func:`backend.app.chat.retrieval.retrieve` / ``build_index`` — BM25
  retrieval over KB chunks.
* :mod:`backend.app.chat.llm` — adapter boundary (deterministic default).
"""

from backend.app.chat.answers import answer, detect_nutrients, format_value
from backend.app.chat.escalation import check
from backend.app.chat.llm import LLMAdapter, TemplateLLM, build_adapter
from backend.app.chat.retrieval import KBIndex, build_index, retrieve

__all__ = [
    "answer",
    "detect_nutrients",
    "format_value",
    "check",
    "LLMAdapter",
    "TemplateLLM",
    "build_adapter",
    "KBIndex",
    "build_index",
    "retrieve",
]
