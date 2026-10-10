"""Chat citation provenance: the first citation must match the answered number.

Covers the grounded chat pipeline (``backend.app.chat.answers``) plus the
``/chat`` endpoint:

* a clinician-edited constraint (CLINICIAN-EDIT trace row) must cite the
  clinician-edit provenance first — the guideline rule that originally fired
  is context at most, never the source of the clinician-authored number, and
  guideline rules that do not apply to the patient's diagnoses must not be
  cited at all;
* a guideline-sourced (unedited) constraint keeps citing the guideline rule
  that produced it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.chat import answers
from backend.app.kb.graph_store import load_kb
from backend.app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "rules" / "rules.json"
DISHES_PATH = _REPO_ROOT / "data" / "dishes.json"

_SODIUM_QUESTION = "What is my daily sodium limit?"


@pytest.fixture(scope="module")
def kb():
    graph = load_kb(RULES_PATH, DISHES_PATH)
    yield graph
    graph.close()


def _ada_sodium_row() -> dict:
    """Fired-rule row for ADA-2026-SODIUM-2300 (as the engine emits it)."""
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
    """CLINICIAN-EDIT trace row (mirrors core/envelope_lifecycle.edit)."""
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


# ---------------------------------------------------------------------------
# Regression: edited value must cite the clinician edit, not the guideline
# ---------------------------------------------------------------------------


def test_edited_sodium_cites_clinician_edit_first(kb) -> None:
    """P0001-style case: T2D patient, sodium MAX edited to 1800 mg by the
    clinician and the envelope re-approved. The answer must quote 1.8 g and
    cite the clinician-edit provenance first; the original guideline rule is
    context at most. CKD rules must not be cited for a T2D-only patient."""
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
    # CKD rules must not be cited for a T2D-only patient.
    assert "CKD-2024-SODIUM-2000" not in rule_ids
    assert rule_ids[0] != "ADA-2026-SODIUM-2300"


def test_edited_sodium_via_api_cites_clinician_edit_first() -> None:
    """Full loop through the API: rules/run -> clinician edit (1800 mg) ->
    re-approve -> chat. The chat answer must quote 1.8 g with the
    CLINICIAN-EDIT citation first and no inapplicable CKD guideline."""
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


# ---------------------------------------------------------------------------
# Guideline-sourced (unedited) constraints keep their guideline citation
# ---------------------------------------------------------------------------


def test_unedited_constraint_still_cites_guideline_rule(kb) -> None:
    """Without a clinician edit the constraint's provenance is the guideline
    rule that fired: the first citation stays the guideline rule."""
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


# ---------------------------------------------------------------------------
# Regression: numeric rule conditions must actually be evaluated
# ---------------------------------------------------------------------------


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
        # Unknown sentinel / missing lab never satisfies the test.
        ("ge", 5.0, -1.0, False),
        ("ge", 5.0, None, False),
    ],
)
def test_rule_applies_to_patient_numeric_ops(op, value, num, expected) -> None:
    """Each known numeric op must be its own branch: a satisfied comparison
    keeps the rule applicable, a failed one rejects it, and the unknown
    sentinel (-1.0) / missing value never satisfies the test.

    Regression: only ``between`` could ever return True — a passing ge/gt/
    le/lt/eq fell through to the ``else: return False``."""
    patient = {"patient_id": "PX", "serum_K_meq_L": num}
    assert answers._rule_applies_to_patient(_numeric_rule("serum_K_meq_L", op, value), patient) is expected


def test_rule_applies_to_patient_unknown_op_rejected() -> None:
    patient = {"patient_id": "PX", "serum_K_meq_L": 5.45}
    assert answers._rule_applies_to_patient(_numeric_rule("serum_K_meq_L", "regex", "5"), patient) is False


def _hyperk_potassium_row() -> dict:
    """Fired-rule row for HYPERK-2024-POTASSIUM-2400 (as the engine emits it)."""
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
    """P0006-style case: serum K 5.45 mEq/L fires HYPERK-2024-POTASSIUM-2400
    (potassium MAX 2400 mg/d). The hyperkalaemia rule must stay applicable and
    be cited — regression: the applicability filter rejected every satisfied
    numeric comparison except ``between``, dropping the rule (and with it the
    KB anchor) even though the rule engine had fired it for this patient."""
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
    # The hyperkalaemia rule is the applicable anchor, so its verbatim quote
    # is quoted in the answer prose.
    assert "restrict dietary potassium in hyperkalaemia" in result["answer"]
    # Rules that do not apply to this patient are never cited.
    assert "CKD-2024-POTASSIUM-INDIV" not in rule_ids
    assert "DASH-2025-POTASSIUM-4700" not in rule_ids