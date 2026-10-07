"""Tests for the explanation view builders (backend/app/explain).

Uses the hand-worked sample trace ``rules/example_trace.json`` (CKD stage 4 +
HTN + hyperkalaemia) as the envelope/trace fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.explain import clinician_explanation, patient_explanation

_REPO_ROOT = Path(__file__).resolve().parents[3]
TRACE_PATH = _REPO_ROOT / "rules" / "example_trace.json"


@pytest.fixture(scope="module")
def sample():
    with open(TRACE_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    envelope = doc["expected_envelope"]
    return envelope, envelope["fired_rules"]


# ---------------------------------------------------------------------------
# Clinician view
# ---------------------------------------------------------------------------


def test_clinician_view_fired_rules(sample) -> None:
    envelope, trace = sample
    view = clinician_explanation(envelope, trace)
    ids = [f["rule_id"] for f in view["fired_rules"]]
    assert "CKD-2024-SODIUM-2000" in ids
    assert "CONFLICT-SODIUM-CKD-WINS" in ids
    assert "HYPERK-2024-POTASSIUM-2400" in ids

    sodium = next(f for f in view["fired_rules"] if f["rule_id"] == "CKD-2024-SODIUM-2000")
    assert sodium["priority"] == 90
    assert sodium["guideline"] == "KDIGO 2024 CKD Guideline"
    assert sodium["section"] == "Sec. 3.4 / Dietary Sodium"
    assert sodium["url"] and sodium["url"].startswith("https://kdigo.org")
    # Ordered by priority DESC, then rule id.
    priorities = [f["priority"] for f in view["fired_rules"]]
    assert priorities == sorted(priorities, reverse=True)


def test_clinician_view_conflicts_resolved(sample) -> None:
    envelope, trace = sample
    view = clinician_explanation(envelope, trace)
    recorded = {c.get("recorded_by") for c in view["conflicts_resolved"]}
    assert "CONFLICT-SODIUM-CKD-WINS" in recorded
    assert "CONFLICT-K-DASH-VS-CKD" in recorded

    # The DASH sodium ceiling was overridden by the higher-priority CKD rule.
    overrides = [c for c in view["conflicts_resolved"] if c.get("overridden")]
    sodium_override = next(
        c for c in overrides
        if any(o["rule_id"] == "DASH-2025-SODIUM-2300" for o in c["overridden"])
    )
    assert sodium_override["winner_rule_id"] == "CKD-2024-SODIUM-2000"
    assert sodium_override["winner_priority"] > 70


def test_clinician_view_constraints_cited(sample) -> None:
    envelope, trace = sample
    view = clinician_explanation(envelope, trace)
    by_nutrient = {c["nutrient"]: c for c in view["constraints"]}

    sodium = by_nutrient["sodium_mg"]
    assert (sodium["kind"], sodium["value"], sodium["unit"]) == ("max", 2000, "mg")
    assert sodium["citation"]["rule_id"] == "CKD-2024-SODIUM-2000"
    assert sodium["citation"]["guideline"] == "KDIGO 2024 CKD Guideline"

    protein = by_nutrient["protein_g"]
    assert protein["citation"]["rule_id"] == "CKD-2024-PROTEIN-055-08"
    potassium = by_nutrient["potassium_mg"]
    assert potassium["citation"]["rule_id"] == "HYPERK-2024-POTASSIUM-2400"
    fiber = by_nutrient["fiber_g"]
    assert fiber["citation"]["rule_id"] == "DASH-2025-FIBER-30"

    # Exclusions carry their original citations.
    excl_values = {e["value"] for e in view["exclusions"]}
    assert "potassium_chloride" in excl_values
    assert all(e["citation"] for e in view["exclusions"])


def test_clinician_view_deterministic(sample) -> None:
    envelope, trace = sample
    assert clinician_explanation(envelope, trace) == clinician_explanation(
        envelope, trace
    )


# ---------------------------------------------------------------------------
# Patient view
# ---------------------------------------------------------------------------


def test_patient_view_plain_language_targets(sample) -> None:
    envelope, _ = sample
    view = patient_explanation(envelope)
    text = " ".join(t["text"] for t in view["daily_targets"])

    # 2000 mg sodium becomes "under 2 g a day" style phrasing.
    assert "Keep salt (sodium) under 2 g a day." in text
    # Energy min+max merged into a range.
    assert "1750 kcal to 2450 kcal" in text
    # Protein as a range (0.55-0.8 g/kg -> 38.5-56 g in this sample).
    assert "at least" in text or "38.5 g to 56 g" in text


def test_patient_view_no_rule_ids_or_jargon(sample) -> None:
    envelope, _ = sample
    dumped = json.dumps(patient_explanation(envelope))
    assert "CKD-2024-SODIUM-2000" not in dumped
    assert "HYPERK-2024" not in dumped
    assert "CONFLICT-" not in dumped
    assert "nutrient" not in dumped or "sodium_mg" not in dumped


def test_patient_view_why_bullets_from_trace_citations(sample) -> None:
    envelope, _ = sample
    view = patient_explanation(envelope)
    assert view["why"], "expected why-bullets from trace citations"
    assert any("KDIGO 2024 CKD Guideline" in b for b in view["why"])
    assert any("2 g" in b for b in view["why"])


def test_patient_view_avoid_list(sample) -> None:
    envelope, _ = sample
    view = patient_explanation(envelope)
    avoid = " | ".join(view["avoid"])
    assert "salt substitutes" in avoid
    assert "high-potassium foods" in avoid
    assert "phosphate additives" in avoid


def test_patient_view_approval_note(sample) -> None:
    envelope, _ = sample  # example trace envelope is PROPOSED
    view = patient_explanation(envelope)
    assert envelope["status"] == "PROPOSED"
    assert view["approval_note"] and "not been approved" in view["approval_note"]

    approved = dict(envelope, status="APPROVED")
    assert patient_explanation(approved)["approval_note"] is None


def test_patient_view_with_plan(sample) -> None:
    envelope, _ = sample
    plan = {"totals": {"sodium_mg": 1800, "protein_g": 50}}
    view = patient_explanation(envelope, plan=plan)
    assert view["plan_summary"]
    joined = " ".join(view["plan_summary"])
    assert "1.8 g of salt (sodium)" in joined
    assert "50 g of protein" in joined

    assert patient_explanation(envelope)["plan_summary"] is None


def test_patient_view_deterministic(sample) -> None:
    envelope, _ = sample
    assert patient_explanation(envelope) == patient_explanation(envelope)