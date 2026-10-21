"""Traceability: every envelope constraint/exclusion cites a fired rule.

Targets and exclusions need a matching trace action with guideline, section,
and rule ID. Count rejected patients separately but still check their exclusions
and trace citations.
"""

from __future__ import annotations

from typing import Any

from evaluation.common import (
    exclusion_supported,
    load_patients,
    target_supported,
)
from rules.engine import run_rules

__all__ = ["evaluate_traceability"]


def _evaluate_patient(patient: dict[str, Any]) -> dict[str, Any]:
    result = run_rules(patient)
    envelope, trace = result["envelope"], result["trace"]
    targets = envelope.get("targets", [])
    exclusions = envelope.get("exclusions", [])

    untraceable: list[dict[str, Any]] = []
    traceable_targets = 0
    for t in targets:
        if target_supported(t, trace):
            traceable_targets += 1
        else:
            untraceable.append({"patient_id": envelope["patient_id"], "item": "target", **t})
    traceable_exclusions = 0
    for e in exclusions:
        if exclusion_supported(e, trace):
            traceable_exclusions += 1
        else:
            untraceable.append(
                {"patient_id": envelope["patient_id"], "item": "exclusion",
                 "kind": e["kind"], "value": e["value"]}
            )

    items = len(targets) + len(exclusions)
    traceable = traceable_targets + traceable_exclusions
    return {
        "patient_id": envelope["patient_id"],
        "status": envelope["status"],
        "targets": len(targets),
        "exclusions": len(exclusions),
        "items": items,
        "traceable": traceable,
        "rate": (traceable / items) if items else None,
        "untraceable": untraceable,
        "fired_rules": len(trace),
    }


def evaluate_traceability(patients: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Traceability of every envelope constraint/exclusion to a cited rule firing."""
    patients = patients if patients is not None else load_patients()
    per_patient = [_evaluate_patient(p) for p in patients]

    eligible = [r for r in per_patient if r["status"] != "REJECTED"]
    rejected = [r for r in per_patient if r["status"] == "REJECTED"]

    total_items = sum(r["items"] for r in eligible)
    total_traceable = sum(r["traceable"] for r in eligible)
    overall_rate = (total_traceable / total_items) if total_items else None

    rejected_exclusion_items = sum(r["exclusions"] for r in rejected)
    rejected_exclusion_traceable = sum(r["traceable"] for r in rejected)

    return {
        "criterion": "Traceability",
        "definition": (
            "Every envelope target and exclusion must be traceable to >=1 fired "
            "trace row carrying a citation (guideline + section + rule_id). "
            "Targets are matched by (nutrient, kind, final value) against the "
            "trace action summaries. This matching is weaker than provenance: "
            "a superseded action whose final value coincides with the target "
            "still matches, so PASS means a cited, value-matching action "
            "exists — not that the matched row is the exact author of the "
            "target."
        ),
        "total_patients": len(per_patient),
        "eligible_patients": len(eligible),
        "rejected_patients": len(rejected),
        "rejected_patient_ids": [r["patient_id"] for r in rejected],
        "rejected_have_no_targets": all(r["targets"] == 0 for r in rejected),
        "rejected_exclusions": {
            "items": rejected_exclusion_items,
            "traceable": rejected_exclusion_traceable,
            "rate": (
                rejected_exclusion_traceable / rejected_exclusion_items
                if rejected_exclusion_items else None
            ),
        },
        "overall": {
            "items": total_items,
            "traceable": total_traceable,
            "rate": overall_rate,
        },
        "per_patient": per_patient,
        "untraceable_items": [u for r in per_patient for u in r["untraceable"]],
        "verdict": "PASS" if overall_rate == 1.0 else "FAIL",
    }
