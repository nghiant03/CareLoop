"""HTTP rule-input validation must precede native execution and persistence."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.api import rules as api_rules
from backend.app.main import app
from rules import engine


def patient(**overrides):
    return {"patient_id": "INPUT-REGRESSION", "age": 62, "sex": "M",
            "weight_kg": 70, "diagnoses": ["CKD_stage_4", "HTN"],
            "egfr": 22, "serum_K_meq_L": 5.8, **overrides}


@pytest.fixture
def client(clinical_test_database):
    with TestClient(app, raise_server_exceptions=False) as connection:
        yield connection


INVALID_FIELDS = [
    ("patient_id", []), ("patient_id", " "),
    ("age", -1), ("age", 131), ("age", []), ("age", {}),
    ("age", None), ("age", True), ("age", 62.5), ("age", "bad"),
    ("sex", "unknown"), ("sex", []), ("sex", None),
    ("weight_kg", None), ("weight_kg", 0), ("weight_kg", -1),
    ("weight_kg", True), ("weight_kg", "NaN"), ("weight_kg", "Infinity"),
    ("diagnoses", "CKD_stage_4"), ("diagnoses", {}),
    ("diagnoses", None), ("diagnoses", [42]), ("diagnoses", [None]),
    ("meds", "ACEi"), ("meds", {}), ("meds", None), ("meds", [42]),
    ("pregnant", "false"), ("pregnant", 1), ("pregnant", []),
]
INVALID_FIELDS += [(field, value)
                   for field in ["egfr", "serum_K_meq_L", "serum_PO4_mg_dL",
                                 "bmi", "hba1c_pct"]
                   for value in [-1, "bad", "NaN", "Infinity", True, []]]


@pytest.mark.parametrize("field,value", INVALID_FIELDS)
def test_invalid_input_is_json_safe_422_before_native_access(client, monkeypatch, field, value):
    def unexpected_environment():
        pytest.fail("invalid rule inputs must not reach the native environment")
    monkeypatch.setattr(engine, "_get_env", unexpected_environment)
    response = client.post("/rules/run", json=patient(**{field: value}))
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"]["error"] == "validation_error"
    json.dumps(body, allow_nan=False)


@pytest.mark.parametrize("field", ["age", "sex", "weight_kg"])
def test_required_inputs_cannot_be_synthesized(client, monkeypatch, field):
    monkeypatch.setattr(engine, "_get_env", lambda: pytest.fail("missing input reached CLIPS"))
    payload = patient()
    del payload[field]
    response = client.post("/rules/run", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "validation_error"


@pytest.mark.parametrize("field", ["weight_kg", "egfr", "serum_K_meq_L", "bmi", "hba1c_pct"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_strict_json_numbers_do_not_leak_into_error_body(client, monkeypatch, field, value):
    monkeypatch.setattr(engine, "_get_env", lambda: pytest.fail("nonfinite input reached CLIPS"))
    response = client.post("/rules/run", content=json.dumps(patient(**{field: value})),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "validation_error"
    json.dumps(response.json(), allow_nan=False)


def test_normalized_aliases_null_precedence_and_richer_inputs_are_preserved(client, monkeypatch):
    received = []
    original = api_rules.engine_run_rules
    def capture(payload):
        received.append(payload)
        return original(payload)
    monkeypatch.setattr(api_rules, "engine_run_rules", capture)
    payload = patient(age="62", weight_kg="70", serum_K_meq_L=None,
                      serum_k_meq_l="ignored-invalid-alias", serum_po4_mg_dl="5",
                      bmi="28", pregnant=False, hba1c_pct="6.2",
                      labs_K_monthly=[4.5, 4.2], archetype="fixture-extra")
    response = client.post("/rules/run", json=payload)
    assert response.status_code == 200, response.text
    validated = received[0]
    assert validated["serum_K_meq_L"] is None
    assert validated["serum_PO4_mg_dL"] == 5
    assert validated["labs_K_monthly"] == payload["labs_K_monthly"]
    assert validated["archetype"] == "fixture-extra"
    snapshot = response.json()["envelope"]["patient_snapshot"]
    assert snapshot["bmi"] == 28
    assert snapshot["pregnant"] is False
    assert snapshot["hba1c_pct"] == 6.2
    assert snapshot["serum_K_meq_L"] is None


@pytest.mark.parametrize("lab", ["serum_k_meq_l", "serum_po4_mg_dl"])
def test_python_lab_aliases_are_validated_when_wire_key_is_absent(client, monkeypatch, lab):
    monkeypatch.setattr(engine, "_get_env", lambda: pytest.fail("bad alias reached CLIPS"))
    payload = patient(**{lab: "bad"})
    payload.pop("serum_K_meq_L", None)
    response = client.post("/rules/run", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("labs", [{}, {"egfr": None, "serum_K_meq_L": None,
                                      "serum_PO4_mg_dL": None}])
def test_missing_and_null_labs_remain_unknown(client, labs):
    payload = patient()
    for key in ["egfr", "serum_K_meq_L", "serum_PO4_mg_dL"]:
        payload.pop(key, None)
    response = client.post("/rules/run", json={**payload, **labs})
    assert response.status_code == 200, response.text
    snapshot = response.json()["envelope"]["patient_snapshot"]
    assert all(snapshot[key] is None for key in ["egfr", "serum_K_meq_L", "serum_PO4_mg_dL"])


def test_fixture_lookup_and_all_rich_inline_records_keep_scope_decisions(client):
    from backend.datasets.paths import dataset_path
    fixtures = json.loads(dataset_path("patients.json").read_text())
    for record in fixtures:
        inline = client.post("/rules/run", json=record)
        lookup = client.post("/rules/run", json={"patient_id": record["patient_id"]})
        assert inline.status_code == lookup.status_code == 200, (inline.text, lookup.text)
        left, right = inline.json()["envelope"], lookup.json()["envelope"]
        assert left["envelope_id"] != right["envelope_id"]
        assert left["status"] == right["status"]
        assert left["scope_eligible"] == right["scope_eligible"]
        assert left["patient_snapshot"] == right["patient_snapshot"]


def test_service_validation_covers_non_http_callers(monkeypatch):
    monkeypatch.setattr(engine, "_get_env", lambda: pytest.fail("invalid service input reached CLIPS"))
    with pytest.raises(api_rules.HTTPException) as failure:
        api_rules.run_rules_service(patient(age=-1))
    assert failure.value.status_code == 422


def test_internal_engine_value_error_is_not_mislabeled_as_client_validation(client, monkeypatch):
    def fail(_patient):
        raise ValueError("internal rule assembly failure")
    monkeypatch.setattr(api_rules, "engine_run_rules", fail)
    response = client.post("/rules/run", json=patient())
    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
