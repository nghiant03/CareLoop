"""Rule-engine endpoint (Week 1 stub).

``POST /rules/run`` accepts a :class:`PatientSummary` and returns a **PROPOSED**
:class:`NutrientEnvelope`. For Week 1 this is a deterministic stub: it
references rule IDs from ``rules/rules.json`` when that file exists but does
**not** call clipspy. Week 2 replaces the body with the real CLIPS rule base
while keeping the response contract identical.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from backend.app.core.approval_gate import put_envelope
from backend.app.models.envelope import (
    CitationSource,
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
    RuleFire,
)

router = APIRouter(prefix="/rules", tags=["rules"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_FILE = _REPO_ROOT / "rules" / "rules.json"

# Fallback rule IDs used when rules/rules.json is not yet present (Lane A).
_FALLBACK_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "CKD-NA-001",
        "guideline": "KDIGO 2024",
        "section": "Chapter 3.2",
        "priority": 90,
        "action": "Na ceiling = 2000 mg/d (CKD overrides DASH/ADA)",
    },
    {
        "rule_id": "ADA-NA-001",
        "guideline": "ADA Standards of Care 2026",
        "section": "Nutrition Consensus",
        "priority": 40,
        "action": "Na ceiling = 2300 mg/d",
    },
    {
        "rule_id": "CKD-PRO-001",
        "guideline": "KDOQI 2020",
        "section": "Protein intake",
        "priority": 80,
        "action": "Protein 0.55-0.8 g/kg/d",
    },
    {
        "rule_id": "HTN-K-001",
        "guideline": "AHA-ACC 2025",
        "section": "DASH potassium",
        "priority": 30,
        "action": "K ~4700 mg/d unless CKD/hyperkalemia",
    },
]


def _summarise_actions(rule: dict[str, Any]) -> str:
    """Turn Lane A's ``actions`` list into a short human-readable summary."""
    explicit = rule.get("action") or rule.get("description")
    if explicit:
        return str(explicit)
    actions = rule.get("actions")
    if isinstance(actions, str):
        return actions
    if not isinstance(actions, list):
        return "stub rule action"
    parts: list[str] = []
    for act in actions:
        if isinstance(act, dict):
            kind = act.get("kind", act.get("type", "set"))
            nutrient = act.get("nutrient")
            value = act.get("value")
            if nutrient is not None:
                parts.append(f"{kind} {nutrient} = {value}")
            else:
                parts.append(str(act.get("type", kind)))
        else:
            parts.append(str(act))
    return "; ".join(parts) or "stub rule action"


def _load_rule_specs() -> list[dict[str, Any]]:
    """Best-effort read of Lane A's rule spec; fall back to stubs."""
    if not RULES_FILE.exists():
        return _FALLBACK_RULES
    try:
        raw = json.loads(RULES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return _FALLBACK_RULES
    rules = raw.get("rules", raw) if isinstance(raw, dict) else raw
    if not isinstance(rules, list) or not rules:
        return _FALLBACK_RULES
    normalised: list[dict[str, Any]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        rid = r.get("rule_id") or r.get("id")
        if not rid:
            continue
        normalised.append(
            {
                "rule_id": str(rid),
                "guideline": str(r.get("guideline", r.get("source", "unspecified"))),
                "section": str(r.get("section", "unspecified")),
                "priority": int(r.get("priority", 0)),
                "action": _summarise_actions(r),
                "url": r.get("url"),
                "verbatim_quote": r.get("verbatim_quote"),
            }
        )
    return normalised or _FALLBACK_RULES


def _citation(spec: dict[str, Any]) -> CitationSource:
    return CitationSource(
        guideline=spec["guideline"],
        section=spec["section"],
        rule_id=spec["rule_id"],
        url=spec.get("url"),
        verbatim_quote=spec.get("verbatim_quote"),
    )


def build_stub_envelope(patient: PatientSummary) -> NutrientEnvelope:
    """Build a deterministic PROPOSED envelope without invoking clipspy."""
    specs = _load_rule_specs()
    by_id = {s["rule_id"]: s for s in specs}

    fired: list[RuleFire] = []
    citations: list[CitationSource] = []
    for spec in specs:
        fired.append(
            RuleFire(
                rule_id=spec["rule_id"],
                fired_at=datetime.now(timezone.utc),
                patient_summary=(
                    f"patient {patient.patient_id}: "
                    f"{', '.join(patient.diagnoses) or 'no diagnoses'}"
                ),
                action_summary=spec["action"] or "stub rule action",
                priority=spec["priority"],
                citation=_citation(spec),
            )
        )
        citations.append(_citation(spec))

    targets = [
        NutrientConstraint(
            nutrient=NutrientKind.ENERGY_KCAL,
            kind=ConstraintKind.TARGET,
            value=round(30.0 * patient.weight_kg, 1),
            unit="kcal",
        ),
        NutrientConstraint(
            nutrient=NutrientKind.PROTEIN_G,
            kind=ConstraintKind.MAX,
            value=round(0.8 * patient.weight_kg, 1),
            unit="g",
        ),
        NutrientConstraint(
            nutrient=NutrientKind.SODIUM_MG,
            kind=ConstraintKind.MAX,
            value=2000.0,
            unit="mg",
        ),
        NutrientConstraint(
            nutrient=NutrientKind.POTASSIUM_MG,
            kind=ConstraintKind.MAX,
            value=3500.0,
            unit="mg",
        ),
    ]

    return NutrientEnvelope(
        envelope_id=f"env-{uuid.uuid4().hex[:12]}",
        patient_id=patient.patient_id,
        status=EnvelopeStatus.PROPOSED,
        version=1,
        patient_snapshot=patient,
        targets=targets,
        exclusions=[],
        fired_rules=fired,
        citations=citations,
        priority_basis="CKD > HTN > T2D on sodium; K/PO4 individualised to labs",
        proposed_by="rules-engine-stub (Week 1; clipspy in Week 2)",
        notes="Week 1 stub envelope. Not clinically validated.",
    )


@router.post("/run", summary="Run the rule engine (Week 1 stub)")
def run_rules(patient: PatientSummary) -> NutrientEnvelope:
    envelope = build_stub_envelope(patient)
    put_envelope(envelope)
    return envelope
