"""Tests for rules.engine.run_rules (run from repo root: .venv/bin/python -m pytest rules/ -q)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rules import clipspy_facts  # must remain importable
from rules.engine import CLIPS_AVAILABLE, run_rules
from shared.envelope_schema import NutrientEnvelope, RuleFire

REPO = Path(__file__).resolve().parents[1]
PATIENTS = json.loads((REPO / "data" / "patients.json").read_text())
EXAMPLE = json.loads((REPO / "rules" / "example_trace.json").read_text())


def _ckd4_htn(k: float = 5.4) -> dict:
    """The hand-worked example_trace.json patient (CKD stage 4 + HTN, 70 kg)."""
    return dict(EXAMPLE["patient_input"], serum_K_meq_L=k)


def _targets(env: dict, nutrient: str, kind: str | None = None) -> list[dict]:
    return [
        t
        for t in env["targets"]
        if t["nutrient"] == nutrient and (kind is None or t["kind"] == kind)
    ]


def _trace(out: dict) -> dict:
    return {row["rule_id"]: row for row in out["trace"]}


# ---------------------------------------------------------------------------
# 1. CKD stage 4 + HTN: KDIGO sodium ceiling beats DASH/ADA, override visible
# ---------------------------------------------------------------------------


def test_ckd4_htn_sodium_kdigo_beats_dash_with_trace_override():
    assert CLIPS_AVAILABLE, "clipspy must be installed for the engine"
    out = run_rules(_ckd4_htn())
    env = out["envelope"]

    sodium_max = _targets(env, "sodium_mg", "max")
    assert len(sodium_max) == 1
    assert sodium_max[0]["value"] == 2000.0  # KDIGO 2000, not DASH/ADA 2300

    trace = _trace(out)
    assert "CKD-2024-SODIUM-2000" in trace
    assert "DASH-2025-SODIUM-2300" in trace
    dash_row = trace["DASH-2025-SODIUM-2300"]
    assert "SUPERSEDED" in dash_row["action_summary"]
    assert "CKD-2024-SODIUM-2000" in dash_row["action_summary"]
    assert trace["DASH-2025-SODIUM-2300"]["priority"] == 70
    assert trace["CKD-2024-SODIUM-2000"]["priority"] == 90
    assert "CONFLICT-SODIUM-CKD-WINS" in trace


# ---------------------------------------------------------------------------
# 2. CKD + normal serum K: no potassium ceiling despite DASH
# ---------------------------------------------------------------------------


def test_ckd_normal_k_no_potassium_max_despite_dash():
    out = run_rules(_ckd4_htn(k=4.2))
    env = out["envelope"]

    assert _targets(env, "potassium_mg") == []  # no K restriction of any kind

    trace = _trace(out)
    assert "DASH-2025-POTASSIUM-4700" not in trace  # its no-CKD guard blocked it
    assert "CONFLICT-K-DASH-NORMAL" in trace
    assert "does not adopt DASH 4700 target" in trace["CONFLICT-K-DASH-NORMAL"]["action_summary"]
    assert "CKD-2024-POTASSIUM-INDIV" in trace
    assert "no blanket" in trace["CKD-2024-POTASSIUM-INDIV"]["action_summary"].lower() or \
        "potassium_restriction=false" in trace["CKD-2024-POTASSIUM-INDIV"]["action_summary"]


# ---------------------------------------------------------------------------
# 3. Hyperkalaemia: potassium max present (and severe tier tightens it)
# ---------------------------------------------------------------------------


def test_hyperkalemia_potassium_max_present():
    patient = _ckd4_htn(k=5.8)
    out = run_rules(patient)
    env = out["envelope"]

    k_max = _targets(env, "potassium_mg", "max")
    assert len(k_max) == 1
    assert k_max[0]["value"] <= 2400.0  # severe tier (>=5.5) tightens to 2000

    trace = _trace(out)
    assert "HYPERK-2024-POTASSIUM-2400" in trace
    assert "SAFETY-HYPERK-SEVERE" in trace  # internal safety rule for K >= 5.5
    if k_max[0]["value"] == 2000.0:
        assert "SUPERSEDED" in trace["HYPERK-2024-POTASSIUM-2400"]["action_summary"]
    # DASH potassium target must be voided by the restriction
    assert _targets(env, "potassium_mg", "target") == []
    assert _targets(env, "potassium_mg", "min") == []


# ---------------------------------------------------------------------------
# 4. T2D-only: sensible defaults
# ---------------------------------------------------------------------------


def test_t2d_only_sensible_defaults():
    patient = {
        "patient_id": "T2D-ONLY",
        "age": 55,
        "sex": "F",
        "weight_kg": 80.0,
        "diagnoses": ["T2D"],
        "egfr": 90.0,
        "serum_K_meq_L": 4.1,
        "serum_PO4_mg_dL": 3.5,
        "meds": ["metformin"],
        "bmi": 28.0,
    }
    out = run_rules(patient)
    env = out["envelope"]

    assert env["status"] == "PROPOSED"
    assert _targets(env, "sodium_mg", "max")[0]["value"] == 2300.0  # ADA
    assert _targets(env, "fiber_g", "target")[0]["value"] == 30.0  # ADA target
    assert _targets(env, "fiber_g", "min")[0]["value"] == 25.0

    energy = {t["kind"]: t["value"] for t in _targets(env, "energy_kcal")}
    assert energy["min"] == pytest.approx(25 * 80.0)  # 25-35 kcal/kg scaled
    assert energy["max"] == pytest.approx(35 * 80.0)

    protein = {t["kind"]: t["value"] for t in _targets(env, "protein_g")}
    assert protein["min"] == pytest.approx(0.8 * 80.0)
    assert protein["target"] == pytest.approx(1.0 * 80.0)

    # T2D exclusions present with citations
    excl_values = {e["value"] for e in env["exclusions"]}
    assert "sugar_sweetened_beverage" in excl_values
    assert all("rule_id" in e["citation"] for e in env["exclusions"])


# ---------------------------------------------------------------------------
# 5. Pregnancy: out-of-scope exclusion, no envelope constraints
# ---------------------------------------------------------------------------


def test_pregnancy_excluded_no_constraints():
    patient = {
        "patient_id": "PREG-1",
        "age": 29,
        "sex": "F",
        "weight_kg": 64.3,
        "diagnoses": ["pregnancy", "T2D"],
        "egfr": 84.7,
        "serum_K_meq_L": 3.9,
        "serum_PO4_mg_dL": 3.6,
        "meds": ["metformin"],
        "bmi": 28.7,
    }
    out = run_rules(patient)
    env = out["envelope"]

    assert env["targets"] == []  # no nutrient constraints proposed
    assert "SCOPE-PREGNANCY-EXCLUDE" in _trace(out)
    kinds = {(e["kind"], e["value"]) for e in env["exclusions"]}
    assert ("diet_pattern", "pregnancy") in kinds
    assert "careloop_eligible=false" in env["notes"]


# ---------------------------------------------------------------------------
# 6. Schema validation across all 20 synthetic patients
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("patient", PATIENTS, ids=lambda p: p["patient_id"])
def test_all_patients_validate_against_frozen_schema(patient):
    out = run_rules(patient)
    envelope = NutrientEnvelope.model_validate(out["envelope"])  # raises if invalid
    for row in out["trace"]:
        RuleFire.model_validate(row)

    if not patient["exclude_from_careloop"]:
        assert envelope.status.value == "PROPOSED"
        assert len(envelope.targets) > 0
    else:
        # out-of-scope patients get no proposed nutrient targets
        assert envelope.targets == []


def test_every_target_traceable_to_a_fired_rule():
    """Every target/exclusion must carry citation info traceable to a fired rule."""
    for patient in PATIENTS:
        out = run_rules(patient)
        env = out["envelope"]
        fired_ids = {row["rule_id"] for row in out["trace"]}
        cited_ids = {c["rule_id"] for c in env["citations"]}
        for target in env["targets"]:
            producers = [
                row for row in out["trace"]
                if row["rule_id"] in fired_ids and target["nutrient"] in row["action_summary"]
                and f"set {target['nutrient']} {target['kind']}" in row["action_summary"]
            ]
            assert producers, f"untraceable target {target} for {patient['patient_id']}"
        for exclusion in env["exclusions"]:
            assert exclusion["citation"]["rule_id"] in fired_ids
        # every fired rule contributes its citation
        assert fired_ids <= cited_ids


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


def test_determinism_same_patient_identical_output():
    patient = PATIENTS[5]  # CKD4_hyperK — rich conflict scenario
    first = run_rules(patient)
    second = run_rules(patient)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# Hand-worked example regression
# ---------------------------------------------------------------------------


def test_example_trace_patient_fires_the_documented_ruleset():
    out = run_rules(EXAMPLE["patient_input"])
    fired = {row["rule_id"] for row in out["trace"]}
    assert fired == set(EXAMPLE["all_fired_rule_ids"])
    env = out["envelope"]
    # Every hand-worked target must be produced; the engine additionally emits
    # the sodium target 1500 from DASH-2025-SODIUM-1500, which is listed in the
    # example's own all_fired_rule_ids but whose set_constraint action was
    # omitted from the hand-worked targets list (it is a soft target, not a
    # hard ceiling). See rules/ENGINE.md, "Deviations".
    expected = {(t["nutrient"], t["kind"], t["value"]) for t in EXAMPLE["expected_envelope"]["targets"]}
    actual = {(t["nutrient"], t["kind"], t["value"]) for t in env["targets"]}
    assert expected <= actual
    sodium_targets = [t for t in actual if t[0] == "sodium_mg" and t[1] == "target"]
    assert sodium_targets == [("sodium_mg", "target", 1500.0)]


# ---------------------------------------------------------------------------
# Ketoacid-risk presentation: clinician-review flag, no auto envelope
# ---------------------------------------------------------------------------


def test_severe_hyperglycemia_suppresses_auto_envelope():
    patient = {
        "patient_id": "DKA-RISK",
        "age": 45,
        "sex": "M",
        "weight_kg": 90.0,
        "diagnoses": ["T2D"],
        "egfr": 85.0,
        "serum_K_meq_L": 4.0,
        "serum_PO4_mg_dL": 3.5,
        "meds": ["insulin"],
        "bmi": 31.0,
        "hba1c_pct": 11.2,
    }
    out = run_rules(patient)
    env = out["envelope"]

    assert env["status"] == "REJECTED"  # no auto envelope
    assert env["targets"] == []
    assert "SAFETY-DKA-CLINICIAN-REVIEW" in _trace(out)
    assert "clinician_review_required=true" in env["notes"]
    assert "AUTO ENVELOPE SUPPRESSED" in env["notes"]


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_clipspy_facts_still_importable():
    assert clipspy_facts.CLIPS_AVAILABLE is True
    fact = clipspy_facts.patient_fact(
        {"patient_id": "X", "age": 50, "sex": "M", "weight_kg": 70.0,
         "diagnoses": ["T2D"], "meds": [], "pregnant": False}
    )
    assert fact.startswith("(patient")


def test_result_contract_shape():
    out = run_rules(PATIENTS[0])
    assert set(out.keys()) == {"envelope", "trace"}
    assert out["envelope"]["status"] == "PROPOSED"
    assert out["envelope"]["version"] == 1
    assert out["envelope"]["patient_id"] == PATIENTS[0]["patient_id"]
    assert all(set(row) == {"rule_id", "fired_at", "patient_summary", "action_summary",
                            "priority", "citation"} for row in out["trace"])