"""Check chat grounding, safety escalation, approval handling, and adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.chat import answers, escalation, llm, retrieval
from backend.app.kb.graph_store import load_kb

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

RULES_PATH = dataset_path("rules.json")
DISHES_PATH = dataset_path("dishes.json")


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
        # Regression cases (safety review): drug names must escalate even
        # when no generic medication word appears in the sentence.
        ("Should I stop taking metformin?", "medication_change"),
        ("Can I skip my insulin today?", "medication_change"),
        ("I want to stop my warfarin", "medication_change"),
        ("Is it safe to quit taking lisinopril?", "medication_change"),
        ("Can I reduce my furosemide?", "medication_change"),
        # Metabolic emergencies.
        ("My blood sugar is 420 and I feel awful", "emergency"),
        ("My sugars are above 300", "emergency"),
        ("I feel dizzy and I have ketones, what should I eat?", "emergency"),
        ("His breath smells fruity — could it be ketoacidosis?", "emergency"),
        ("My speech is slurred since this morning", "emergency"),
        # Upper tail of the emergency glucose category (floor 350 mg/dL):
        # any direct reading at or above the floor escalates, unbounded.
        ("My blood sugar is 500; how much carbohydrate should I eat?", "emergency"),
        ("my blood sugar is 499", "emergency"),
        ("my blood sugar was 1000", "emergency"),
        ("my blood sugar reading was 1000 mg/dL", "emergency"),
        ("my sugars are 1050 tonight", "emergency"),
        # Unit-aware readings convert mmol/L (x18) to the same mg/dL floor.
        ("my blood sugar is 27.8 mmol/L", "emergency"),
        ("glucose 500 mg/dL on my meter", "emergency"),
        ("my glucose reading is 19.5 mmol/l", "emergency"),
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
        # Guard against over-escalation from the new drug/metabolic patterns.
        "How much sugar is in a can of cola?",
        "What are the guidelines about carbohydrates per day?",
        # Boundary guards for the emergency glucose category: readings below
        # the configured floor stay in scope (no invented lower thresholds).
        "My blood sugar is 349 this morning",
        "my blood sugar is 19.4 mmol/L",
        "my sugars are above 250",
    ],
)
def test_escalation_in_scope(question: str) -> None:
    result = escalation.check(question)
    assert result["escalate"] is False
    assert result["reason"] is None


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


def test_grounded_sodium_answer_cites_kb_ceiling(kb) -> None:
    """No envelope is supplied: the 2000 mg ceiling is KB-derived from the
    KDIGO rule chain (envelope-number behaviour is covered separately)."""
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


def test_irrelevant_question_refused(kb) -> None:
    result = answers.answer("What is the capital of France?", kb)
    assert result["status"] == "refused"
    assert result["citations"] == []
    assert "clinician" in result["answer"].lower()


def test_unsupported_intake_question_refused_independent_of_phrasing(kb) -> None:
    """Refuse unsupported sugar targets even without legacy intake keywords."""
    result = answers.answer("What should my sugar intake be?", kb)
    assert result["status"] == "refused"
    assert result["citations"] == []

    with_patient = answers.answer(
        "What should my sugar intake be?", kb,
        patient={"patient_id": "P0001", "diagnoses": ["T2D"], "weight_kg": 61.6},
    )
    assert with_patient["status"] == "refused"
    assert with_patient["citations"] == []


def test_escalation_wins_over_answer(kb) -> None:
    result = answers.answer("I have chest pain — what should I eat?", kb)
    assert result["status"] == "escalated"
    assert result["citations"] == []


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


def test_proposed_envelope_never_quotes_plan_numbers(kb) -> None:
    """Safety policy: only APPROVED envelope numbers may be quoted.

    The PROPOSED answer must not present the plan's own values (2000 mg
    sodium / 56 g protein) as the patient's limits.
    """
    result = answers.answer("how much salt and protein can I have?", kb, envelope=_envelope("PROPOSED"))
    assert result["status"] == "answered"
    assert "2000" not in result["answer"]
    assert result["envelope"]["approved"] is False


def test_edited_envelope_never_quotes_plan_numbers(kb) -> None:
    result = answers.answer("why is my sodium limit 2000?", kb, envelope=_envelope("EDITED"))
    assert result["status"] == "answered"
    assert "not been approved" in result["answer"]
    assert "2000" not in result["answer"]


def test_rejected_envelope_gets_fixed_declined_response(kb) -> None:
    """Out-of-scope (REJECTED) envelope: one fixed, respectful response —
    regardless of the question, with no numbers and no guideline content."""
    envelope = _envelope("REJECTED")
    for question in (
        "how much potassium can I have?",
        "what should I eat for dinner?",
        "What is the capital of France?",
    ):
        result = answers.answer(question, kb, envelope=envelope)
        assert result["status"] == "refused", question
        assert "declined" in result["answer"]
        assert "clinician" in result["answer"]
        assert result["citations"] == []
        # no plan numbers, no guideline quotes leak through
        assert "2000" not in result["answer"]
        assert "56" not in result["answer"]
        assert result["envelope"] is None


def test_approved_per_kg_envelope_scaled_by_known_weight(kb) -> None:
    """A per-kg envelope coefficient must never be quoted as an absolute
    daily dose; with a known weight the computed daily value is shown."""
    envelope = _envelope("APPROVED")
    envelope["targets"].append(
        {"nutrient": "energy_kcal", "kind": "max", "value": 35, "unit": "kcal"}
    )
    envelope["fired_rules"].append(
        {
            "rule_id": "CKD-2024-ENERGY-2535",
            "action_summary": "set energy_kcal max = 35 kcal/kg/d (weight unknown; not scaled)",
            "priority": 80,
            "citation": {
                "rule_id": "CKD-2024-ENERGY-2535",
                "guideline": "KDIGO 2024 CKD Guideline",
                "section": "Sec. 3.11 / Energy",
                "url": None,
                "verbatim_quote": None,
            },
        }
    )
    result = answers.answer(
        "how many calories can I have?",
        kb,
        envelope=envelope,
        patient={"patient_id": "SYN-0007", "weight_kg": 70.0},
    )
    assert result["status"] == "answered"
    assert "2450" in result["answer"]  # 35 kcal/kg x 70 kg
    assert "35 kcal per day" not in result["answer"]


def test_per_kg_envelope_without_weight_says_per_kg(kb) -> None:
    """Without a known weight the raw coefficient is rendered per kg of body
    weight — never as '... per day'."""
    envelope = _envelope("APPROVED")
    envelope["targets"] = [
        {"nutrient": "energy_kcal", "kind": "max", "value": 35, "unit": "kcal"}
    ]
    envelope["fired_rules"] = [
        {
            "rule_id": "CKD-2024-ENERGY-2535",
            "action_summary": "set energy_kcal max = 35 kcal/kg/d (weight unknown; not scaled)",
            "priority": 80,
            "citation": {
                "rule_id": "CKD-2024-ENERGY-2535",
                "guideline": "KDIGO 2024 CKD Guideline",
                "section": "Sec. 3.11 / Energy",
                "url": None,
                "verbatim_quote": None,
            },
        }
    ]
    result = answers.answer("how many calories can I have?", kb, envelope=envelope)
    assert result["status"] == "answered"
    assert "per kg of body weight" in result["answer"]
    assert "35 kcal per day" not in result["answer"]


def _clinician_energy_envelope(with_provenance: bool) -> dict:
    """APPROVED envelope whose energy target is an absolute clinician
    replacement (2100 kcal) while a legacy raw coefficient trace row from the
    original proposal survives in ``fired_rules``."""
    target: dict = {"nutrient": "energy_kcal", "kind": "target", "value": 2100, "unit": "kcal"}
    if with_provenance:
        target["provenance"] = {
            "nutrient": "energy_kcal",
            "kind": "target",
            "value": 2100,
            "unit": "kcal",
            "citation": {
                "rule_id": "CLINICIAN-EDIT",
                "guideline": "clinician override",
                "section": "clinician edit",
                "url": None,
                "verbatim_quote": None,
            },
        }
    return {
        "envelope_id": "ENV-TEST-EDIT",
        "patient_id": "SYN-0007",
        "status": "APPROVED",
        "targets": [target],
        "fired_rules": [
            {
                "rule_id": "CKD-2024-ENERGY-2535",
                "action_summary": "set energy_kcal target = 30 kcal/kg/d (weight unknown; not scaled)",
                "priority": 80,
                "citation": {
                    "rule_id": "CKD-2024-ENERGY-2535",
                    "guideline": "KDIGO 2024 CKD Guideline",
                    "section": "Sec. 3.11 / Energy",
                    "url": None,
                    "verbatim_quote": None,
                },
            },
            {
                "rule_id": "CLINICIAN-EDIT",
                "action_summary": "clinician override: targets replaced (set energy_kcal target = 2100 kcal)",
                "priority": 0,
                "citation": {
                    "rule_id": "CLINICIAN-EDIT",
                    "guideline": "clinician override",
                    "section": "clinician edit",
                    "url": None,
                    "verbatim_quote": None,
                },
            },
        ],
        "citations": [],
    }


def test_clinician_replacement_not_rescaled_by_legacy_trace(kb) -> None:
    """Regression (legacy trace): an absolute clinician replacement must not
    be multiplied by body weight when an older raw per-kg coefficient trace
    row remains — clinician provenance wins."""
    envelope = _clinician_energy_envelope(with_provenance=True)
    result = answers.answer(
        "how many calories can I have?", kb,
        envelope=envelope, patient={"patient_id": "SYN-0007", "weight_kg": 70.0},
    )
    assert result["status"] == "answered"
    assert "2100 kcal" in result["answer"]
    assert "147000" not in result["answer"]  # 2100 x 70 kg must never appear
    rule_ids = [c.get("rule_id") for c in result["citations"]]
    assert "CLINICIAN-EDIT" in rule_ids


def test_absolute_target_with_mismatched_legacy_trace_not_rescaled(kb) -> None:
    """Legacy trace compatibility without provenance: a coefficient row only
    counts when it produced the stored value, so a 2100 kcal target next to a
    30 kcal/kg/d row stays absolute (no weight multiplication)."""
    envelope = _clinician_energy_envelope(with_provenance=False)
    result = answers.answer(
        "how many calories can I have?", kb,
        envelope=envelope, patient={"patient_id": "SYN-0007", "weight_kg": 70.0},
    )
    assert result["status"] == "answered"
    assert "2100 kcal" in result["answer"]
    assert "147000" not in result["answer"]


def test_guideline_per_kg_constraints_rendered_per_kg(kb) -> None:
    """KB rulebook constraints for energy/protein are per-kg coefficients:
    the answer must say 'per kg of body weight' (or scale by the patient's
    weight), never '35 kcal per day'."""
    result = answers.answer("how many calories should I eat?", kb)
    assert result["status"] == "answered"
    assert "per kg of body weight" in result["answer"]
    assert "35 kcal per day" not in result["answer"]
    assert "25 kcal per day" not in result["answer"]

    scaled = answers.answer(
        "how many calories should I eat?", kb, patient={"weight_kg": 70.0}
    )
    assert "1750" in scaled["answer"]  # 25 kcal/kg x 70 kg
    assert "2450" in scaled["answer"]  # 35 kcal/kg x 70 kg


def test_patient_anchor_never_cites_internal_rules(kb) -> None:
    """CONFLICT-*/SAFETY-* are internal policy, not patient-facing guideline
    anchors: the patient-role citation set must not use them as anchors."""
    result = answers.answer("how much protein can I have?", kb, role="patient")
    if result["status"] == "answered":
        for citation in result["citations"]:
            rule_id = citation.get("rule_id") or ""
            assert not rule_id.startswith(("CONFLICT-", "SAFETY-")), rule_id


def test_no_citation_fallback_to_unrelated_rule(kb) -> None:
    """A sodium citation cannot support a clinician-authored protein value."""
    envelope = _envelope("APPROVED")
    envelope["targets"] = [
        {"nutrient": "protein_g", "kind": "max", "value": 56, "unit": "g"}
    ]
    # fired_rules still only mention sodium (as after a clinician edit).
    result = answers.answer("how much protein can I have?", kb, envelope=envelope)
    assert result["status"] == "answered"
    rule_ids = [c.get("rule_id") for c in result["citations"]]
    assert "CKD-2024-SODIUM-2000" not in rule_ids


def test_untraceable_personal_value_withheld_not_anchor_cited(kb) -> None:
    """Withhold the untraceable 1800 mg target without borrowing the 2000 mg source."""
    envelope = _envelope("APPROVED")
    envelope["targets"] = [
        {"nutrient": "sodium_mg", "kind": "max", "value": 1800, "unit": "mg"}
    ]
    # fired_rules still produce 2000 mg (value does not match the target).
    result = answers.answer("why is my sodium limit 2000?", kb, envelope=envelope)
    assert result["status"] == "answered"
    assert "1.8 g" not in result["answer"]
    assert "1800" not in result["answer"]
    sources = [claim.get("source") for claim in result.get("claims", [])]
    assert "envelope" not in sources
    # The guideline anchor still grounds the answer itself.
    assert result["citations"]


def test_approved_notice_follows_lifecycle_not_question_match(kb) -> None:
    """Regression (summary consistency): an APPROVED envelope must never
    carry the pending-approval notice, even when the question targets a
    nutrient the envelope does not cover (no envelope context is built)."""
    envelope = _envelope("APPROVED")  # sodium + protein targets
    result = answers.answer("how much potassium can I have?", kb, envelope=envelope)
    assert result["status"] == "answered"
    assert result["envelope"]["approved"] is True
    assert result["envelope"]["notice"] is None


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
