"""Shared helpers for the evaluation suite.

These helpers load fixtures and inspect traces without writing application state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
PATIENTS_PATH = ROOT / "data" / "patients.json"
RULES_PATH = ROOT / "rules" / "rules.json"

# Per-kg nutrients are scaled by weight during assembly (see rules/engine.py).
PER_KG_NUTRIENTS = {"energy_kcal", "protein_g"}

# Matches one ``set <nutrient> <kind> = <value> <unit>/d`` piece of a trace
# ``action_summary``; per-kg rules additionally carry ``-> <scaled> <unit>/d``.
_SET_PIECE = re.compile(
    r"set (?P<nutrient>\w+) (?P<kind>\w+) = (?P<value>-?[\d.]+) (?P<unit>[\w/]+?/d)"
    r"(?:\s+->\s+(?P<final>-?[\d.]+))?"
)


def load_patients() -> list[dict[str, Any]]:
    """Load synthetic patient fixtures from data/patients.json in stored order."""
    with open(PATIENTS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def citation_complete(citation: Optional[dict[str, Any]]) -> bool:
    """A citation is usable when rule_id + guideline + section are all present."""
    if not isinstance(citation, dict):
        return False
    return bool(citation.get("rule_id")) and bool(citation.get("guideline")) and bool(citation.get("section"))


def fired_rule_ids(trace: list[dict[str, Any]]) -> set[str]:
    return {row["rule_id"] for row in trace}


def is_superseded(trace: list[dict[str, Any]], rule_id: str) -> bool:
    """True when ``rule_id``'s trace row carries a SUPERSEDED marker."""
    return any(
        row["rule_id"] == rule_id and "SUPERSEDED" in row.get("action_summary", "")
        for row in trace
    )


def targets_of(
    envelope: dict[str, Any],
    nutrient: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[dict[str, Any]]:
    out = []
    for t in envelope.get("targets", []):
        if nutrient is not None and t["nutrient"] != nutrient:
            continue
        if kind is not None and t["kind"] != kind:
            continue
        out.append(t)
    return out


def target_value(
    envelope: dict[str, Any], nutrient: str, kind: str
) -> Optional[float]:
    found = targets_of(envelope, nutrient, kind)
    return found[0]["value"] if found else None


def has_target(envelope: dict[str, Any], nutrient: str, kind: str) -> bool:
    return bool(targets_of(envelope, nutrient, kind))


def target_supported(target: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    """Is this envelope target traceable to a fired rule with a full citation?

    Match nutrient and kind, then compare the final value within 0.005 to
    tolerate trace rounding. Per-kg actions use the scaled ``-> final`` value.
    The citation must carry guideline, section, and rule ID. This checks for a
    matching cited action, not exact provenance or units. A SUPERSEDED marker
    does not exclude an otherwise matching row.
    """
    nutrient, kind = target["nutrient"], target["kind"]
    expected = float(target["value"])
    for row in trace:
        summary = row.get("action_summary", "")
        for match in _SET_PIECE.finditer(summary):
            if match["nutrient"] != nutrient or match["kind"] != kind:
                continue
            final_raw = match["final"] if match["final"] is not None else match["value"]
            try:
                final = float(final_raw)
            except ValueError:  # pragma: no cover - defensive
                continue
            if abs(final - expected) <= 0.005 and citation_complete(row.get("citation")):
                return True
    return False


def exclusion_supported(exclusion: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    """Is this exclusion traceable to a fired rule with a full citation?"""
    citation = exclusion.get("citation") or {}
    return (
        citation.get("rule_id") in fired_rule_ids(trace)
        and citation_complete(citation)
    )
