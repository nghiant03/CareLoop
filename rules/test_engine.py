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
# Dialysis / stage 5: out of scope even when eGFR is missing
# ---------------------------------------------------------------------------


def _dialysis_patient(**overrides) -> dict:
    patient = {
        "patient_id": "ESRD-1",
        "age": 58,
        "sex": "M",
        "weight_kg": 70.0,
        "diagnoses": ["ESRD", "T2D"],
        "serum_K_meq_L": 4.2,
        "serum_PO4_mg_dL": 3.4,
        "meds": [],
        "bmi": 26.0,
    }
    patient.update(overrides)
    return patient


def test_dialysis_excluded_even_without_egfr():
    """Regression: diagnosis alone must fire the scope gate — a missing eGFR
    used to let dialysis patients slip through with a normal PROPOSED
    envelope (the old rule ANDed the diagnosis with egfr < 15)."""
    out = run_rules(_dialysis_patient())  # no egfr key at all
    env = out["envelope"]

    assert env["status"] == "REJECTED"
    assert env["targets"] == []
    assert "SCOPE-DIALYSIS-EXCLUDE" in _trace(out)
    assert "careloop_eligible=false" in env["notes"]
    # Fail-safe: the unevaluable lab-only scope gate is surfaced, not silent.
    assert "scope_lab_unknown=SCOPE-EGFR-STAGE5-EXCLUDE:egfr" in env["notes"]


def test_dialysis_excluded_with_stale_high_egfr():
    """A recorded eGFR must not veto the dialysis diagnosis."""
    out = run_rules(_dialysis_patient(egfr=68.0))
    assert out["envelope"]["status"] == "REJECTED"
    assert "SCOPE-DIALYSIS-EXCLUDE" in _trace(out)


def test_stage5_egfr_lab_only_detection():
    """Lab-only path: measured eGFR < 15 is out of scope without a diagnosis."""
    out = run_rules(_dialysis_patient(diagnoses=["T2D"], egfr=12.0))
    env = out["envelope"]
    assert env["status"] == "REJECTED"
    assert env["targets"] == []
    assert "SCOPE-EGFR-STAGE5-EXCLUDE" in _trace(out)


def test_unknown_egfr_alone_does_not_exclude():
    """An unknown eGFR must not fabricate an exclusion for patients without a
    stage-5 diagnosis — the lab-only rule stays guarded by the sentinel."""
    out = run_rules(_dialysis_patient(diagnoses=["T2D"]))  # no egfr
    env = out["envelope"]
    assert env["status"] == "PROPOSED"
    assert "SCOPE-EGFR-STAGE5-EXCLUDE" not in _trace(out)


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


# ---------------------------------------------------------------------------
# Medication-nutrient interaction rules
# ---------------------------------------------------------------------------

MED_RULES = {
    "MED-RASI-K-CAUTION": {"meds": ["lisinopril"], "priority": 85},
    "MED-RASI-KSPARING-ALERT": {"meds": ["ACEi", "spironolactone"], "priority": 88},
    "MED-SGLT2I-VOLUME": {"meds": ["SGLT2i"], "priority": 65},
    "MED-THIAZIDE-ELECTROLYTES": {"meds": ["thiazide"], "priority": 70},
    "MED-LOOP-K-MG": {"meds": ["loop_diuretic"], "priority": 70},
    "MED-PHOSPHATE-BINDER-TIMING": {"meds": ["phosphate_binder"], "priority": 65},
    "MED-WARFARIN-VITK": {"meds": ["warfarin"], "priority": 75},
    "MED-METFORMIN-B12": {"meds": ["metformin"], "priority": 60},
}


def _med_patient(meds: list[str], **overrides) -> dict:
    patient = {
        "patient_id": "MED-TEST",
        "age": 60,
        "sex": "F",
        "weight_kg": 70.0,
        "diagnoses": ["T2D"],
        "egfr": 70.0,
        "serum_K_meq_L": 4.2,
        "serum_PO4_mg_dL": 3.5,
        "meds": meds,
        "bmi": 27.0,
        "pregnant": False,
    }
    patient.update(overrides)
    return patient


def test_rasi_plus_k_sparing_diuretic_fires_both_flags_with_citations():
    """ACEi/ARB + spironolactone: the MHRA combination alert AND the general
    RASi potassium caution must both fire, each with a full citation, and the
    flags must surface in the envelope notes."""
    out = run_rules(_med_patient(["lisinopril", "spironolactone"]))
    trace = _trace(out)
    env = out["envelope"]

    rasi = trace["MED-RASI-K-CAUTION"]
    assert rasi["priority"] == 85
    assert rasi["citation"]["guideline"] == "KDIGO 2024 CKD Guideline"
    assert rasi["citation"]["section"] == "3.11 / Hyperkalemia in CKD (Practice Point 3.6.3)"
    assert rasi["citation"]["verbatim_quote"]

    combo = trace["MED-RASI-KSPARING-ALERT"]
    assert combo["priority"] == 88
    assert combo["citation"]["guideline"] == "UK MHRA Drug Safety Update 2020"
    assert combo["citation"]["url"].startswith("https://www.gov.uk/drug-safety-update/")

    # flags surface in the notes/cautions line of the envelope
    assert "rasi_k_monitoring=" in env["notes"]
    assert "rasi_k_sparing_interaction=" in env["notes"]
    assert "med_interaction_high_risk=" in env["notes"]


def test_metformin_only_fires_b12_flag_and_no_other_new_med_flag():
    out = run_rules(_med_patient(["metformin"]))
    trace = _trace(out)
    env = out["envelope"]

    assert "MED-METFORMIN-B12" in trace
    b12 = trace["MED-METFORMIN-B12"]
    assert b12["citation"]["guideline"] == "ADA Standards of Care in Diabetes 2026"
    assert b12["citation"]["section"] == "3 / Recommendation 3.10"
    assert "metformin_b12_assessment=" in env["notes"]

    others = set(MED_RULES) - {"MED-METFORMIN-B12"}
    assert others.isdisjoint(trace)


def test_patient_without_relevant_meds_fires_no_med_rules():
    for patient in (PATIENTS[8], PATIENTS[17]):  # healthy controls, meds == []
        out = run_rules(patient)
        assert not [r for r in _trace(out) if r.startswith("MED-")]


@pytest.mark.parametrize("rule_id", sorted(MED_RULES))
def test_each_new_med_rule_fires_with_full_citation(rule_id):
    spec = MED_RULES[rule_id]
    out = run_rules(_med_patient(spec["meds"]))
    trace = _trace(out)

    assert rule_id in trace
    row = trace[rule_id]
    assert row["priority"] == spec["priority"]
    citation = row["citation"]
    assert citation["rule_id"] == rule_id
    assert citation["guideline"]
    assert citation["section"]
    # every new med rule also contributes its citation to the envelope
    assert citation in out["envelope"]["citations"]


def test_med_combo_patient_deterministic():
    first = run_rules(_med_patient(["lisinopril", "spironolactone"]))
    second = run_rules(_med_patient(["lisinopril", "spironolactone"]))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_real_dataset_patient_triggers_at_least_two_new_med_rules():
    """P0006 (CKD4 + hyperkalaemia; meds ACEi + phosphate_binder + ...) must
    fire both the cited RASi potassium rule and the binder-timing rule from
    the live dataset vocabulary."""
    patient = next(p for p in PATIENTS if p["patient_id"] == "P0006")
    out = run_rules(patient)
    trace = _trace(out)
    fired_new = set(MED_RULES) & set(trace)
    assert {"MED-RASI-K-CAUTION", "MED-PHOSPHATE-BINDER-TIMING"} <= fired_new
    for rid in fired_new:
        assert trace[rid]["citation"]["guideline"]
        assert trace[rid]["citation"]["section"]


def test_example_trace_regression_includes_new_med_rules():
    """The SYN-0007 fixture with ACEi and loop_diuretic fires both cited med rules.

    Its expected firing list must include the medication cautions.
    """
    assert len(json.loads((REPO / "rules" / "example_trace.json").read_text(encoding="utf-8"))["all_fired_rule_ids"]) == 32
