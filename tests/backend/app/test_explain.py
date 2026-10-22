from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.explain import clinician_explanation, patient_explanation

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

TRACE_PATH = dataset_path("example_trace.json")


@pytest.fixture(scope="module")
def sample():
    with open(TRACE_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    envelope = doc["expected_envelope"]
    return envelope, envelope["fired_rules"]


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
    priorities = [f["priority"] for f in view["fired_rules"]]
    assert priorities == sorted(priorities, reverse=True)


def test_clinician_view_conflicts_resolved(sample) -> None:
    envelope, trace = sample
    view = clinician_explanation(envelope, trace)
    recorded = {c.get("recorded_by") for c in view["conflicts_resolved"]}
    assert "CONFLICT-SODIUM-CKD-WINS" in recorded
    assert "CONFLICT-K-DASH-VS-CKD" in recorded

    overlaps = view["priority_overlaps"]
    sodium_overlap = next(
        c for c in overlaps
        if any(o["rule_id"] == "DASH-2025-SODIUM-2300" for o in c["lower_priority_mentions"])
    )
    assert sodium_overlap["highest_priority_rule_id"] == "CKD-2024-SODIUM-2000"
    assert sodium_overlap["highest_priority"] > 70


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

    excl_values = {e["value"] for e in view["exclusions"]}
    assert "potassium_chloride" in excl_values
    assert all(e["citation"] for e in view["exclusions"])


def test_clinician_view_deterministic(sample) -> None:
    envelope, trace = sample
    assert clinician_explanation(envelope, trace) == clinician_explanation(
        envelope, trace
    )


def test_patient_view_plain_language_targets(sample) -> None:
    envelope, _ = sample
    view = patient_explanation(envelope)
    text = " ".join(t["text"] for t in view["daily_targets"])

    assert "Keep sodium under 2 g a day." in text
    assert "1750 kcal to 2450 kcal" in text
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
    envelope, _ = sample
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
    assert "1.8 g of sodium" in joined
    assert "50 g of protein" in joined

    assert patient_explanation(envelope)["plan_summary"] is None


def test_patient_view_non_round_bounds_keep_precision(sample) -> None:
    envelope, _ = sample
    edited = deepcopy(envelope)
    for target in edited["targets"]:
        if target["nutrient"] == "sodium_mg" and target["kind"] == "max":
            target["value"] = 1550
        if target["nutrient"] == "protein_g" and target["kind"] == "min":
            target["value"] = 27.5
    view = patient_explanation(edited)
    text = " ".join(t["text"] for t in view["daily_targets"])
    assert "Keep sodium under 1.55 g a day." in text
    assert "Keep sodium under 1.6 g a day." not in text
    assert "Aim for 27.5 g to 56 g of protein a day." in text

    for target in edited["targets"]:
        if target["nutrient"] == "sodium_mg" and target["kind"] == "max":
            target["value"] = 1555
    text = " ".join(t["text"] for t in patient_explanation(edited)["daily_targets"])
    assert "Keep sodium under 1555 mg a day." in text


def test_patient_view_clinician_edited_target_not_authored_to_guideline(sample) -> None:
    envelope, _ = sample
    edited = deepcopy(envelope)
    for target in edited["targets"]:
        if target["nutrient"] == "sodium_mg":
            target["value"] = 1800
            target["provenance"] = {
                "nutrient": "sodium_mg",
                "kind": target["kind"],
                "value": 1800,
                "unit": "mg",
                "envelope_id": envelope["envelope_id"],
                "version": 2,
                "author": "dr-tan",
                "citation": {
                    "rule_id": "CLINICIAN-EDIT",
                    "guideline": "clinician override",
                    "section": "clinician edit",
                    "url": None,
                    "verbatim_quote": None,
                },
            }
    view = patient_explanation(edited)

    sodium_bullets = [bullet for bullet in view["why"] if "sodium" in bullet]
    assert sodium_bullets == ["Your care team set: keep sodium under 1.8 g a day."]
    assert not any("KDIGO" in bullet and "sodium" in bullet for bullet in view["why"])
    assert any("recommends" in bullet for bullet in view["why"] if "sodium" not in bullet)


def test_patient_view_deterministic(sample) -> None:
    envelope, _ = sample
    assert patient_explanation(envelope) == patient_explanation(envelope)
