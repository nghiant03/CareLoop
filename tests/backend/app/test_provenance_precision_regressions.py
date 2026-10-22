from pathlib import Path

import pytest

from backend.app.chat import answers
from backend.app.explain.views import clinician_explanation, patient_explanation
from backend.app.kb.graph_store import load_kb

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def kb():
    from backend.datasets.paths import dataset_path
    graph = load_kb(dataset_path("rules.json"), dataset_path("dishes.json"))
    yield graph
    graph.close()


def _citation(rule_id="TEST-SODIUM"):
    return {
        "rule_id": rule_id,
        "guideline": "Test dietary guideline",
        "section": "Sodium",
        "url": "https://example.test/sodium",
        "verbatim_quote": "Use the exact approved sodium bound.",
    }


def _envelope(kind="max", value=1800, *, provenance_value=None):
    citation = _citation()
    target = {"nutrient": "sodium_mg", "kind": kind, "value": value, "unit": "mg"}
    if provenance_value is not None:
        target["provenance"] = {
            **target,
            "value": provenance_value,
            "envelope_id": "ENV-TEST-001",
            "version": 1,
            "author": "rules-engine",
            "citation": citation,
        }
    trace = {
        "rule_id": "TEST-SODIUM",
        "action_summary": f"set sodium_mg {kind} = {value} mg/d",
        "priority": 10,
        "citation": citation,
    }
    return {
        "envelope_id": "ENV-TEST-001",
        "patient_id": "P-TEST",
        "status": "APPROVED",
        "version": 1,
        "targets": [target],
        "fired_rules": [trace],
    }


def test_stale_explicit_provenance_is_not_replaced_by_trace(kb):
    envelope = _envelope("max", 1800, provenance_value=2000)
    target = envelope["targets"][0]

    clinician = clinician_explanation(envelope, envelope["fired_rules"])
    patient = patient_explanation(envelope)
    chat = answers.answer("What is my daily sodium limit?", kb, envelope=envelope)

    assert clinician["constraints"][0]["citation"] is None
    assert clinician["constraints"][0]["provenance"]["value"] == 2000
    assert not any("sodium" in reason.lower() for reason in patient["why"])
    assert chat["status"] == "answered"
    assert not any(claim.get("source") == "envelope" for claim in chat["claims"])
    assert "1.8 g" not in chat["answer"]
    assert target["value"] == 1800


@pytest.mark.parametrize(
    ("kind", "question", "expected_phrase"),
    [
        ("max", "What is my daily sodium limit?", "1555.128456 mg"),
        ("min", "How much sodium should I get each day?", "1555.128456 mg"),
    ],
)
def test_high_precision_bounds_are_lossless_across_views(
    kb, kind, question, expected_phrase
):
    envelope = _envelope(kind, 1555.128456, provenance_value=1555.128456)

    clinician = clinician_explanation(envelope, envelope["fired_rules"])
    patient = patient_explanation(envelope)
    chat = answers.answer(question, kb, envelope=envelope)

    assert clinician["constraints"][0]["value"] == 1555.128456
    assert clinician["constraints"][0]["citation"] == _citation()
    target_text = " ".join(row["text"] for row in patient["daily_targets"])
    assert expected_phrase in target_text
    assert "1555.128456" in chat["answer"]
    assert "1.55513 g" not in chat["answer"]
    assert any(claim.get("source") == "envelope" for claim in chat.get("claims", []))
