from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.chat import answers
from backend.app.kb.graph_store import load_kb
from backend.app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

RULES_PATH = dataset_path("rules.json")
DISHES_PATH = dataset_path("dishes.json")

_SODIUM_QUESTION = "What is my daily sodium limit?"


@pytest.fixture(scope="module")
def kb():
    graph = load_kb(RULES_PATH, DISHES_PATH)
    yield graph
    graph.close()


def _ada_sodium_row() -> dict:
    return {
        "rule_id": "ADA-2026-SODIUM-2300",
        "action_summary": "set sodium_mg max = 2300 mg/d",
        "priority": 60,
        "citation": {
            "rule_id": "ADA-2026-SODIUM-2300",
            "guideline": "ADA Standards of Care 2026",
            "section": "Sec. 5.9 / Medical Nutrition Therapy",
            "url": "https://diabetesjournals.org/care",
            "verbatim_quote": "reduce sodium intake to less than 2,300 mg per day",
        },
    }


def _clinician_edit_row(value: int = 1800) -> dict:
    return {
        "rule_id": "CLINICIAN-EDIT",
        "action_summary": (
            f"clinician override: targets replaced (set sodium_mg max = {value} mg)"
        ),
        "priority": 0,
        "citation": {
            "rule_id": "CLINICIAN-EDIT",
            "guideline": "clinician override",
            "section": "clinician edit",
            "url": None,
            "verbatim_quote": None,
        },
    }


def _kdigo_sodium_row() -> dict:
    return {
        "rule_id": "CKD-2024-SODIUM-2000",
        "action_summary": "set sodium_mg max = 2000 mg/d",
        "priority": 90,
        "citation": {
            "rule_id": "CKD-2024-SODIUM-2000",
            "guideline": "KDIGO 2024 CKD Guideline",
            "section": "Sec. 3.4 / Dietary Sodium",
            "url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
            "verbatim_quote": "recommend sodium intake less than 2 g per day",
        },
    }


def test_edited_sodium_cites_clinician_edit_first(kb) -> None:
    envelope = {
        "envelope_id": "ENV-P0001-001",
        "patient_id": "P0001",
        "status": "APPROVED",
        "targets": [
            {"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"},
        ],
        "fired_rules": [_ada_sodium_row(), _clinician_edit_row(1800)],
        "citations": [],
    }
    patient = {"patient_id": "P0001", "diagnoses": ["T2D"], "weight_kg": 61.6}

    result = answers.answer(_SODIUM_QUESTION, kb, envelope=envelope, patient=patient)

    assert result["status"] == "answered"
    assert "1.8 g" in result["answer"]
    assert result["answer"].startswith(
        "Your clinician-approved plan sets a daily salt (sodium) limit of 1.8 g."
    )

    rule_ids = [c["rule_id"] for c in result["citations"]]
    assert rule_ids, "answered answer must carry citations"
    assert rule_ids[0] == "CLINICIAN-EDIT", rule_ids
    assert "CKD-2024-SODIUM-2000" not in rule_ids
    assert rule_ids[0] != "ADA-2026-SODIUM-2300"


def test_edited_sodium_via_api_cites_clinician_edit_first() -> None:
    with TestClient(app) as client:
        body = client.post("/rules/run", json={"patient_id": "P0019"}).json()
        envelope_id = body["envelope"]["envelope_id"]

        edited = client.post(
            f"/envelopes/{envelope_id}/edit",
            json={
                "targets": [
                    {"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"}
                ],
                "edited_by": "dr-tan",
                "notes": "tightened sodium",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["status"] == "EDITED"

        approved = client.post(
            f"/envelopes/{envelope_id}/approve",
            json={"clinician_id": "dr-tan", "note": "re-approved after edit"},
        )
        assert approved.status_code == 200, approved.text

        resp = client.post(
            "/chat", json={"patient_id": "P0019", "message": _SODIUM_QUESTION}
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["status"] == "answered"
        assert payload["escalated"] is False
        assert "1.8 g" in payload["answer"]

        rule_ids = [c["rule_id"] for c in payload["citations"]]
        assert rule_ids, "answered chat must cite"
        assert rule_ids[0] == "CLINICIAN-EDIT", rule_ids
        assert "CKD-2024-SODIUM-2000" not in rule_ids


def test_unedited_constraint_still_cites_guideline_rule(kb) -> None:
    envelope = {
        "envelope_id": "ENV-P0005-001",
        "patient_id": "P0005",
        "status": "APPROVED",
        "targets": [
            {"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"},
        ],
        "fired_rules": [_kdigo_sodium_row()],
        "citations": [],
    }
    patient = {
        "patient_id": "P0005",
        "diagnoses": ["T2D", "HTN", "CKD_stage_4"],
        "weight_kg": 70.0,
    }

    result = answers.answer(_SODIUM_QUESTION, kb, envelope=envelope, patient=patient)

    assert result["status"] == "answered"
    assert "2 g" in result["answer"]
    rule_ids = [c["rule_id"] for c in result["citations"]]
    assert rule_ids[0] == "CKD-2024-SODIUM-2000", rule_ids
    assert "CLINICIAN-EDIT" not in rule_ids


def _numeric_rule(field: str, op: str, value) -> dict:
    return {"rule_id": "TEST-RULE", "conditions": [{"field": field, "op": op, "value": value}]}


@pytest.mark.parametrize(
    ("op", "value", "num", "expected"),
    [
        ("ge", 5.0, 5.45, True),
        ("ge", 5.0, 4.9, False),
        ("gt", 5.0, 5.0, False),
        ("gt", 5.0, 5.1, True),
        ("le", 5.0, 4.9, True),
        ("le", 5.0, 5.0, True),
        ("le", 5.0, 5.1, False),
        ("lt", 5.0, 5.0, False),
        ("lt", 5.0, 4.9, True),
        ("eq", 5.0, 5.0, True),
        ("eq", 5.0, 5.1, False),
        ("between", [18.0, 25.0], 20.0, True),
        ("between", [18.0, 25.0], 30.0, False),
        ("ge", 5.0, -1.0, False),
        ("ge", 5.0, None, False),
    ],
)
def test_rule_applies_to_patient_numeric_ops(op, value, num, expected) -> None:
    patient = {"patient_id": "PX", "serum_K_meq_L": num}
    assert answers._rule_applies_to_patient(_numeric_rule("serum_K_meq_L", op, value), patient) is expected


def test_rule_applies_to_patient_unknown_op_rejected() -> None:
    patient = {"patient_id": "PX", "serum_K_meq_L": 5.45}
    assert answers._rule_applies_to_patient(_numeric_rule("serum_K_meq_L", "regex", "5"), patient) is False


def _hyperk_potassium_row() -> dict:
    return {
        "rule_id": "HYPERK-2024-POTASSIUM-2400",
        "action_summary": "set potassium_mg max = 2400 mg/d",
        "priority": 85,
        "citation": {
            "rule_id": "HYPERK-2024-POTASSIUM-2400",
            "guideline": "KDIGO 2024 CKD Guideline",
            "section": "Sec. 3.7 / Potassium",
            "url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
            "verbatim_quote": "restrict dietary potassium in hyperkalaemia",
        },
    }


def test_hyperkalaemia_potassium_rule_cited_for_high_serum_k(kb) -> None:
    envelope = {
        "envelope_id": "ENV-P0006-001",
        "patient_id": "P0006",
        "status": "APPROVED",
        "targets": [
            {"nutrient": "potassium_mg", "kind": "max", "value": 2400, "unit": "mg"},
        ],
        "fired_rules": [_hyperk_potassium_row()],
        "citations": [],
    }
    patient = {
        "patient_id": "P0006",
        "diagnoses": ["T2D", "CKD_stage_4", "hyperkalemia"],
        "serum_K_meq_L": 5.45,
        "egfr": 31.2,
        "weight_kg": 70.0,
    }

    result = answers.answer(
        "How much potassium should I eat each day?", kb, envelope=envelope, patient=patient
    )

    assert result["status"] == "answered"
    assert "2.4 g" in result["answer"]
    rule_ids = [c["rule_id"] for c in result["citations"]]
    assert rule_ids, "answered answer must carry citations"
    assert "HYPERK-2024-POTASSIUM-2400" in rule_ids
    assert "restrict dietary potassium in hyperkalaemia" in result["answer"]
    assert "CKD-2024-POTASSIUM-INDIV" not in rule_ids
    assert "DASH-2025-POTASSIUM-4700" not in rule_ids
