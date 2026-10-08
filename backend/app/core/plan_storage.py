"""Persist mapped plan documents with their approved inputs and source hashes."""

import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

from backend.app.core import persistence
from backend.app.core.kb_loader import get_kb
from shared.envelope_schema import NutrientEnvelope

logger = logging.getLogger("careloop.plans")


def _kb_version() -> str:
    try:
        stats = get_kb().stats()
        return str(stats.get("current_version") or f"nodes:{sum(stats.get('node_counts', {}).values())}")
    except Exception as exc:
        logger.warning("knowledge base version unavailable: %s", exc)
        return "unknown"


def try_save_plan_document(response: dict[str, Any], envelope: NutrientEnvelope) -> None:
    """Save a mapped response and attach its plan ID/timestamp in place.

    Storage failure is logged and leaves the generated response available to the
    caller without a saved ID. Both generation and swaps use this behavior.
    """
    try:
        root = Path(__file__).resolve().parents[3]
        response["source_hashes"] = {
            name: sha256((root / name).read_bytes()).hexdigest()
            for name in ("data/dishes.json", "rules/rules.json")
        }
        response["approved_envelope"] = envelope.model_dump(mode="json", by_alias=True)
        plan_id = persistence.save_plan(
            patient_id=str(response.get("patient_id") or envelope.patient_id),
            envelope_id=envelope.envelope_id, envelope_version=envelope.version,
            engine=response.get("engine"), feasible=bool(response.get("feasible")),
            violation_count=int(response.get("violation_count") or 0),
            objectives=response.get("objectives"), days=response.get("days"),
            adequacy=response.get("adequacy"), kb_version=_kb_version(), document=response,
        )
        stored = persistence.get_plan(plan_id)
        response["plan_id"] = plan_id
        response["saved_at"] = stored["saved_at"] if stored else None
    except Exception as exc:
        logger.warning("plan persistence failed: %s", exc)
