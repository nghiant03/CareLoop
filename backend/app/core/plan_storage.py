"""Persist mapped plan documents with their approved inputs and source hashes."""

import logging
from typing import Any

from backend.app.core import persistence
from backend.app.core.kb_loader import get_kb
from backend.knowledge.runtime import selected_release, source_hashes
from shared.envelope_schema import NutrientEnvelope

logger = logging.getLogger("careloop.plans")


def _kb_version() -> str:
    release = selected_release()
    if release is not None:
        return release.release_id
    try:
        stats = get_kb().stats()
        return str(stats.get("current_version") or f"nodes:{sum(stats.get('node_counts', {}).values())}")
    except Exception as exc:  # noqa: BLE001  # best-effort version label
        logger.warning("knowledge base version unavailable: %s", exc)
        return "unknown"


def try_save_plan_document(response: dict[str, Any], envelope: NutrientEnvelope) -> None:
    """Save a mapped response and attach its plan ID/timestamp in place.

    Log failures without blocking generation or swaps. Added hashes and envelope
    metadata remain on failure. A post-save read can fail after commit, so an
    absent response ID does not prove that nothing was persisted.
    """
    try:
        response["source_hashes"] = source_hashes()
        release = selected_release()
        if release is not None:
            response["knowledge_release_id"] = release.release_id
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
    except Exception as exc:  # noqa: BLE001  # persistence must not block plan generation
        logger.warning("plan persistence failed: %s", exc)
