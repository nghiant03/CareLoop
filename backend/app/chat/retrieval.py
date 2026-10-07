"""TF-IDF retrieval over the knowledge base.

Chunks the KB into citable units:

* **rule chunks** — one per current rule; text is built from guideline, section,
  verbatim quote, notes and the constraint actions (with plain-language
  synonyms for nutrients and bound kinds so user phrasing matches);
* **dish chunks** — one per current dish with a nutrient-profile summary.

The index uses scikit-learn's ``TfidfVectorizer`` (documented default for the
prototype per ``rules/SCHEMA_DECISION.md`` scale; embeddings per
``backend/app/core/llm_choice.py`` can replace it later without changing the
chunk contract). Every chunk carries its citable ids so downstream answers can
be fully grounded.
"""

from __future__ import annotations

from typing import Any, Optional, Union
from weakref import WeakKeyDictionary

from sklearn.feature_extraction.text import TfidfVectorizer

from backend.app.kb.graph_store import KBGraph

__all__ = ["Chunk", "KBIndex", "build_index", "retrieve", "MIN_SCORE"]

# Cosine similarity below this is treated as "no grounded match".
MIN_SCORE = 0.05

# Plain-language synonyms appended to chunk/query text so TF-IDF matches
# everyday phrasing ("salt", "calories", "fibre") to canonical nutrients.
_NUTRIENT_SYNONYMS: dict[str, str] = {
    "sodium_mg": "sodium salt na mg",
    "potassium_mg": "potassium k mg",
    "phosphorus_mg": "phosphorus phosphate mg",
    "protein_g": "protein g",
    "energy_kcal": "energy calories kcal",
    "fiber_g": "fiber fibre g",
    "sat_fat_g": "saturated fat satfat",
    "carbs_g": "carbs carbohydrate carbohydrate g",
    "fat_g": "fat g",
    "sugar_g": "sugar g",
}

_KIND_SYNONYMS: dict[str, str] = {
    "max": "limit ceiling maximum under no more than",
    "min": "at least minimum floor",
    "target": "target aim about",
}

Chunk = dict[str, Any]
IndexSource = Union[KBGraph, "KBIndex"]


def _rule_text(rule: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = [
        str(rule.get("guideline") or ""),
        str(rule.get("section") or ""),
        str(rule.get("verbatim_quote") or ""),
        str(rule.get("notes") or ""),
    ]
    nutrients: list[dict[str, Any]] = []
    for action in rule.get("actions", []):
        if action.get("type") != "set_constraint":
            continue
        nutrient = str(action.get("nutrient", ""))
        kind = str(action.get("kind", ""))
        value = action.get("value")
        unit = action.get("unit") or ""
        nutrients.append(
            {"nutrient": nutrient, "kind": kind, "value": value, "unit": unit}
        )
        parts.append(nutrient)
        parts.append(_NUTRIENT_SYNONYMS.get(nutrient, nutrient))
        parts.append(str(kind))
        parts.append(_KIND_SYNONYMS.get(kind, kind))
        parts.append(f"{value} {unit}")
    return " ".join(p for p in parts if p), nutrients


def _dish_text(dish: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parts: list[str] = [
        str(dish.get("name") or ""),
        str(dish.get("category") or ""),
        str(dish.get("cuisine") or ""),
        " ".join(dish.get("tags") or []),
    ]
    profile = dish.get("profile") or {}
    nutrient_bits: dict[str, Any] = {}
    for nutrient, synonyms in _NUTRIENT_SYNONYMS.items():
        value = profile.get(nutrient)
        if value is None:
            continue
        nutrient_bits[nutrient] = value
        parts.append(nutrient)
        parts.append(synonyms)
        parts.append(f"{value}")
    return " ".join(p for p in parts if p), nutrient_bits


class KBIndex:
    """TF-IDF index over KB rule + dish chunks."""

    def __init__(self, kb: KBGraph) -> None:
        self.chunks: list[Chunk] = []
        for rule in kb.rules():
            text, nutrients = _rule_text(rule)
            self.chunks.append(
                {
                    "chunk_id": f"rule:{rule['rule_id']}",
                    "kind": "rule",
                    "text": text,
                    "citation": {
                        "rule_id": rule["rule_id"],
                        "guideline": rule.get("guideline"),
                        "section": rule.get("section"),
                        "url": rule.get("url"),
                        "verbatim_quote": rule.get("verbatim_quote"),
                    },
                    "meta": {
                        "priority": rule.get("priority", 0),
                        "nutrients": nutrients,
                    },
                }
            )
        for dish in kb.dishes():
            text, nutrient_bits = _dish_text(dish)
            self.chunks.append(
                {
                    "chunk_id": f"dish:{dish.get('dish_id')}",
                    "kind": "dish",
                    "text": text,
                    "citation": None,
                    "meta": {
                        "dish_id": dish.get("dish_id"),
                        "name": dish.get("name"),
                        "nutrients": nutrient_bits,
                    },
                }
            )
        corpus = [c["text"] for c in self.chunks]
        if not corpus:
            corpus = ["empty knowledge base"]
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform(corpus)

    def _expand_query(self, query: str) -> str:
        expanded = [query]
        lowered = query.lower()
        for nutrient, synonyms in _NUTRIENT_SYNONYMS.items():
            head = nutrient.rsplit("_", 1)[0]
            if head in lowered or any(
                f" {word} " in f" {lowered} " for word in synonyms.split()
            ):
                expanded.append(f"{nutrient} {synonyms}")
        return " ".join(expanded)

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Return the top-``k`` chunks ranked by TF-IDF cosine similarity.

        Each hit is the chunk dict plus a ``score`` field. Chunks with score 0
        (no vocabulary overlap) are omitted.
        """
        if not query.strip():
            return []
        vec = self._vectorizer.transform([self._expand_query(query)])
        scores = (vec @ self._matrix.T).toarray()[0]
        ranked = sorted(
            (
                (float(score), idx)
                for idx, score in enumerate(scores)
                if score > 0.0
            ),
            key=lambda pair: (-pair[0], self.chunks[pair[1]]["chunk_id"]),
        )
        hits = []
        for score, idx in ranked[: max(k, 0)]:
            hit = dict(self.chunks[idx])
            hit["score"] = score
            hits.append(hit)
        return hits


_CACHE: "WeakKeyDictionary[KBGraph, KBIndex]" = WeakKeyDictionary()


def build_index(kb: KBGraph) -> KBIndex:
    """Build (or fetch the cached) TF-IDF index for a KBGraph."""
    index = _CACHE.get(kb)
    if index is None:
        index = KBIndex(kb)
        _CACHE[kb] = index
    return index


def retrieve(kb: KBGraph, query: str, k: int = 5) -> list[dict[str, Any]]:
    """Convenience one-shot retrieval against a knowledge base."""
    return build_index(kb).retrieve(query, k=k)