"""Tests for the retrieval-grounded chat pipeline (backend/app/chat).

Covers: grounded answer with mandatory KDIGO citation, escalation filter,
low-confidence refusal, and envelope-aware answers (APPROVED numbers served,
PROPOSED flagged as not yet approved). Also the deterministic LLM adapter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.chat import answers, escalation, llm, retrieval
from backend.app.kb.graph_store import load_kb

_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "rules" / "rules.json"
DISHES_PATH = _REPO_ROOT / "data" / "dishes.json"


@pytest.fixture(scope="module")
def kb():
    graph = load_kb(RULES_PATH, DISHES_PATH)
    yield graph
    graph.close()


def _envelope(status: str) -> dict:
    return {
        "envelope_id": "ENV-TEST-1",
        "patient_id": "SYN-0007",
        "status": status,
        "targets": [
            {"nutrient": "sodium_mg", "kind": "max", "value": 2000, "unit": "mg"},
            {"nutrient": "protein_g", "kind": "max", "value": 56, "unit": "g"},
        ],
        "fired_rules": [
            {
                "rule_id": "CKD-2024-SODIUM-2000",
                "action_summary": "Na ceiling = 2000 mg/d",
                "priority": 90,
                "citation": {
                    "rule_id": "CKD-2024-SODIUM-2000",
                    "guideline": "KDIGO 2024 CKD Guideline",
                    "section": "Sec. 3.4 / Dietary Sodium",
                    "url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
                    "verbatim_quote": "recommend sodium intake less than 2 g per day",
                },
            }
        ],
        "citations": [],
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_retrieve_ranks_sodium_rule_first(kb) -> None:
    hits = retrieval.retrieve(kb, "why is my sodium limit 2000?", k=5)
    assert hits, "expected at least one hit"
    top = hits[0]
    assert top["kind"] == "rule"
    assert top["citation"]["rule_id"] == "CKD-2024-SODIUM-2000"
    assert top["score"] > retrieval.MIN_SCORE
    for hit in hits:
        assert hit["score"] > 0
        assert set(hit["citation"] or {}) >= {
            "rule_id", "guideline", "section", "url", "verbatim_quote",
        } or hit["kind"] == "dish"


def test_retrieve_unknown_terms_returns_nothing(kb) -> None:
    hits = retrieval.retrieve(kb, "quantum flurbigibber zyx", k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# Escalation filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,category",
    [
        ("I have crushing chest pain right now", "emergency"),
        ("I feel short of breath and dizzy", "emergency"),
        ("Should I double my metformin dose?", "medication_change"),
        ("Can I stop taking my tablets?", "medication_change"),
        ("Please prescribe something for my swelling", "medication_change"),
        ("Do I have kidney failure?", "diagnosis"),
        ("What's wrong with me, doctor?", "diagnosis"),
        ("I am pregnant, what should I eat?", "out_of_scope"),
        ("My baby needs a diet plan", "out_of_scope"),
    ],
)
def test_escalation_out_of_scope(question: str, category: str) -> None:
    result = escalation.check(question)
    assert result["escalate"] is True
    assert result["category"] == category
    assert result["reason"]


@pytest.mark.parametrize(
    "question",
    [
        "why is my sodium limit 2000?",
        "What can I cook for dinner tonight?",
        "How much fibre should I eat?",
    ],
)
def test_escalation_in_scope(question: str) -> None:
    result = escalation.check(question)
    assert result["escalate"] is False
    assert result["reason"] is None


# ---------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------


def test_grounded_question_cites_kdigo(kb) -> None:
    result = answers.answer("why is my sodium limit 2000?", kb)
    assert result["status"] == "answered"
    assert "KDIGO" in result["answer"]
    rule_ids = [c["rule_id"] for c in result["citations"]]
    assert "CKD-2024-SODIUM-2000" in rule_ids
    for citation in result["citations"]:
        assert citation["rule_id"]
        assert citation["guideline"]
        assert citation["section"]


def test_grounded_question_reflects_envelope_number(kb) -> None:
    result = answers.answer("how much salt can I have?", kb)
    assert result["status"] == "answered"
    # KB answer cites the 2000 mg ceiling from the KDIGO rule chain.
    assert "2 g" in result["answer"] or "2000" in result["answer"]


def test_patient_view_hides_rule_ids(kb) -> None:
    clinician = answers.answer("why is my sodium limit 2000?", kb, role="clinician")
    patient = answers.answer("why is my sodium limit 2000?", kb, role="patient")
    assert "CKD-2024-SODIUM-2000" in clinician["answer"]
    assert "CKD-2024-SODIUM-2000" not in patient["answer"]


def test_answers_deterministic(kb) -> None:
    a1 = answers.answer("why is my sodium limit 2000?", kb)
    a2 = answers.answer("why is my sodium limit 2000?", kb)
    assert a1 == a2


# ---------------------------------------------------------------------------
# Refusal on low confidence
# ---------------------------------------------------------------------------


def test_irrelevant_question_refused(kb) -> None:
    result = answers.answer("What is the capital of France?", kb)
    assert result["status"] == "refused"
    assert result["citations"] == []
    assert "clinician" in result["answer"].lower()


def test_escalation_wins_over_answer(kb) -> None:
    result = answers.answer("I have chest pain — what should I eat?", kb)
    assert result["status"] == "escalated"
    assert result["citations"] == []


# ---------------------------------------------------------------------------
# Envelope-aware answers
# ---------------------------------------------------------------------------


def test_approved_envelope_numbers_served(kb) -> None:
    result = answers.answer("why is my sodium limit 2000?", kb, envelope=_envelope("APPROVED"))
    assert result["status"] == "answered"
    assert "2000" in result["answer"] or "2 g" in result["answer"]
    assert "approved" in result["answer"].lower()
    assert result["envelope"]["approved"] is True
    assert result["envelope"]["notice"] is None
    rule_ids = [c["rule_id"] for c in result["citations"]]
    assert "CKD-2024-SODIUM-2000" in rule_ids


def test_proposed_envelope_flagged_not_approved(kb) -> None:
    result = answers.answer("why is my sodium limit 2000?", kb, envelope=_envelope("PROPOSED"))
    assert result["status"] == "answered"
    assert "not been approved" in result["answer"]
    assert result["envelope"]["approved"] is False
    assert result["envelope"]["notice"]


# ---------------------------------------------------------------------------
# LLM adapter boundary
# ---------------------------------------------------------------------------


def test_template_llm_deterministic() -> None:
    adapter = llm.TemplateLLM()
    a1 = adapter.generate("Answer:", {"fact": "sodium max 2000 mg"})
    a2 = adapter.generate("Answer:", {"fact": "sodium max 2000 mg"})
    assert a1 == a2
    assert "sodium max 2000 mg" in a1


def test_protocol_and_default_adapter() -> None:
    adapter, info = llm.build_adapter(env={})
    assert isinstance(adapter, llm.LLMAdapter)
    assert info["active"] == llm.TemplateLLM.name
    # Documented default (no API keys): local Ollama is the *resolved* choice,
    # while the deterministic template adapter is what actually serves.
    assert info["resolved"]["provider"] == "ollama"


def test_openai_key_resolves_in_metadata() -> None:
    _, info = llm.build_adapter(env={"OPENAI_API_KEY": "sk-test"})
    assert info["resolved"]["provider"] == "openai"
    assert info["resolved"]["model"] == "gpt-4o-mini"
    assert info["active"] == llm.TemplateLLM.name


def test_answer_with_llm_adapter_remains_deterministic(kb) -> None:
    adapter = llm.TemplateLLM()
    r1 = answers.answer("why is my sodium limit 2000?", kb, llm=adapter)
    r2 = answers.answer("why is my sodium limit 2000?", kb, llm=adapter)
    assert r1 == r2
    assert r1["citations"][0]["rule_id"] == "CKD-2024-SODIUM-2000"