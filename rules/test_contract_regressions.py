"""Regression fences for rule inputs, native state and shared reader contracts."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import clips
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from rules import engine
from shared.envelope_schema import (
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)


def patient(**overrides):
    return {"patient_id": "REGRESSION", "age": 62, "sex": "M", "weight_kg": 70,
            "diagnoses": ["CKD_stage_4", "HTN", "T2D"], "egfr": 22,
            "serum_K_meq_L": 5.8, "serum_PO4_mg_dL": 5, **overrides}


@pytest.mark.parametrize("diagnoses", [["HTN"], ["CKD_stage_4"],
                                      ["CKD_stage_4", "HTN", "T2D"]])
@pytest.mark.parametrize("potassium", [5.5, 5.8])
def test_severe_potassium_ceiling_is_exact_and_owned_by_safety(diagnoses, potassium):
    result = engine.run_rules(patient(diagnoses=diagnoses, serum_K_meq_L=potassium))
    targets = result["envelope"]["targets"]
    assert next(t["value"] for t in targets if t["nutrient"] == "potassium_mg") == 2000
    safety = next(r for r in result["trace"] if r["rule_id"] == "SAFETY-HYPERK-SEVERE")
    assert "SUPERSEDED" not in safety["action_summary"]
    conflict = [r for r in result["trace"] if r["rule_id"] == "CONFLICT-K-DASH-VS-CKD"]
    assert all("set potassium_mg" not in r["action_summary"] for r in conflict)


@pytest.mark.parametrize("egfr", [None, 90])
def test_legacy_stage_five_diagnosis_owns_scope_rejection(egfr):
    result = engine.run_rules(patient(diagnoses=["CKD_stage_5_pre_dialysis"], egfr=egfr))
    assert result["envelope"]["status"] == "REJECTED"
    assert result["envelope"]["scope_eligible"] is False
    assert result["envelope"]["targets"] == []
    assert "SCOPE-DIALYSIS-EXCLUDE" in {r["rule_id"] for r in result["trace"]}


@pytest.mark.parametrize("weight", [None, 0, -1, float("nan"), float("inf"), -float("inf"), "bad"])
def test_invalid_weight_fails_before_native_environment(monkeypatch, weight):
    def unexpected_environment():
        pytest.fail("invalid input must not reach CLIPS")
    monkeypatch.setattr(engine, "_get_env", unexpected_environment)
    with pytest.raises(ValueError, match="weight_kg must be finite and positive"):
        engine.run_rules(patient(weight_kg=weight))


@pytest.mark.parametrize("kind,expected", [("max", 100), ("min", 200), ("target", 100)])
def test_equal_priority_kind_policy(kind, expected):
    candidates = [{"nutrient": "sodium_mg", "kind": kind, "value": value,
                   "priority": 50, "rule_id": rid}
                  for value, rid in [(100, "B"), (200, "A"), (100, "C")]]
    winners, losses = engine._resolve_conflicts(candidates)
    winner = winners[("sodium_mg", kind)]
    assert winner["value"] == expected
    assert winner["rule_id"] == ("A" if kind == "min" else "B")
    if kind != "min":
        assert "C" not in losses  # equal values merge, regardless of rule ID
    high_priority = {**candidates[0], "priority": 99, "value": 150, "rule_id": "Z"}
    winners, _ = engine._resolve_conflicts(candidates + [high_priority])
    assert winners[("sodium_mg", kind)]["value"] == 150


def test_concurrent_native_runs_match_serial_outputs(monkeypatch):
    patients = [patient(patient_id=f"PAR-{n}", weight_kg=50 + n,
                        serum_K_meq_L=4.2 if n % 2 else 5.8) for n in range(24)]
    expected = [engine.run_rules(p) for p in patients]
    # Exercise lazy initialization as well as interleaved per-patient operations.
    monkeypatch.setattr(engine, "_ENV", None)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(engine.run_rules, patients)) == expected


def test_native_cleanup_and_lock_release_after_failure(monkeypatch):
    original = engine._harvest
    def fail(_env):
        raise RuntimeError("harvest failure")
    monkeypatch.setattr(engine, "_harvest", fail)
    with pytest.raises(RuntimeError, match="harvest failure"):
        engine.run_rules(patient())
    assert list(engine._ENV.facts()) == []
    monkeypatch.setattr(engine, "_harvest", original)
    assert engine.run_rules(patient())["envelope"]["status"] == "PROPOSED"


@pytest.mark.parametrize("inputs", [{"bmi": 35, "hba1c_pct": 11.2, "pregnant": False},
                                     {"bmi": 28, "hba1c_pct": 6, "pregnant": True}])
def test_version_two_snapshot_replays_rule_inputs(inputs):
    result = engine.run_rules(patient(**inputs))
    snapshot = result["envelope"]["patient_snapshot"]
    assert snapshot["snapshot_version"] == 2
    assert all(snapshot[key] == value for key, value in inputs.items())
    replay = engine.run_rules(PatientSummary.model_validate(snapshot).model_dump(by_alias=True))
    assert replay == result


def test_legacy_snapshot_does_not_invent_new_inputs():
    legacy = {key: value for key, value in patient().items()
              if key in {"patient_id", "age", "sex", "weight_kg", "diagnoses", "egfr",
                         "serum_K_meq_L", "serum_PO4_mg_dL"}}
    original = dict(legacy)
    summary = PatientSummary.model_validate(legacy)
    assert summary.snapshot_version == 1
    assert summary.bmi is summary.pregnant is summary.hba1c_pct is None
    assert legacy == original


@pytest.mark.parametrize("nutrient", list(NutrientKind))
@pytest.mark.parametrize("unit", ["kcal", "g", "mg", "litres"])
def test_json_and_python_unit_reader_parity(nutrient, unit):
    envelope = engine.run_rules(patient())["envelope"]
    target = {"nutrient": nutrient.value, "kind": "max", "value": 1, "unit": unit}
    envelope["targets"] = [target]
    canonical = "kcal" if nutrient == NutrientKind.ENERGY_KCAL else "mg" if nutrient.value.endswith("_mg") else "g"
    schema = json.loads(Path("shared/envelope_schema.json").read_text())
    errors = list(Draft202012Validator(schema).iter_errors(envelope))
    assert bool(errors) == (unit != canonical)
    if unit == canonical:
        NutrientConstraint.model_validate(target)
        NutrientEnvelope.model_validate(envelope)
    else:
        with pytest.raises(ValidationError):
            NutrientEnvelope.model_validate(envelope)


def test_reference_templates_load_and_accept_patient():
    from rules.clipspy_facts import load_templates, patient_fact
    env = clips.Environment()
    load_templates(env)
    assert len(list(env.templates())) == 6
    env.assert_string(patient_fact(patient()))
    assert next(iter(env.facts()))["patient_id"] == "REGRESSION"
    env.reset()


def test_http_lab_spellings_are_equivalent_and_keep_fresh_identity():
    from backend.app.main import app
    wire = patient()
    python_names = dict(wire)
    python_names["serum_k_meq_l"] = python_names.pop("serum_K_meq_L")
    python_names["serum_po4_mg_dl"] = python_names.pop("serum_PO4_mg_dL")
    with TestClient(app) as client:
        responses = [client.post("/rules/run", json=p) for p in [wire, python_names]]
    assert all(r.status_code == 200 for r in responses)
    first, second = [r.json()["envelope"] for r in responses]
    assert first["envelope_id"] != second["envelope_id"]
    for key in ["patient_snapshot", "status", "scope_eligible", "fired_rules"]:
        assert first[key] == second[key]
    # Provenance follows each fresh proposal identity, not the input spelling.
    for envelope in [first, second]:
        for target in envelope["targets"]:
            if target["provenance"]:
                assert target["provenance"]["envelope_id"] == envelope["envelope_id"]
    def without_identity(target):
        copied = {**target, "provenance": dict(target["provenance"]) if target["provenance"] else None}
        if copied["provenance"]:
            copied["provenance"].pop("envelope_id")
        return copied
    assert [without_identity(t) for t in first["targets"]] == [without_identity(t) for t in second["targets"]]


def test_alias_precedence_including_explicit_null():
    both = patient(serum_k_meq_l=6, serum_K_meq_L=None)
    result = engine.run_rules(both)
    assert result["envelope"]["patient_snapshot"]["serum_K_meq_L"] is None
    assert not any(t["nutrient"] == "potassium_mg" for t in result["envelope"]["targets"])


@pytest.mark.parametrize("weight", [None, 0, -1, "NaN", "Infinity"])
def test_http_invalid_weight_is_validation_error(weight):
    from backend.app.main import app
    with TestClient(app) as client:
        response = client.post("/rules/run", json=patient(weight_kg=weight))
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "validation_error"
