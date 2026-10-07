"""Versioned knowledge-base graph store (SQLite + NetworkX prototype).

Implements the logical model from ``rules/neo4j_schema_design.md`` per the
decision in ``rules/SCHEMA_DECISION.md``.
"""

from backend.app.kb.graph_store import KBGraph, load_kb, unit_for_nutrient

__all__ = ["KBGraph", "load_kb", "unit_for_nutrient"]