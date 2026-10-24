import pytest
from test_patients import CLINICIAN, approve, patient, propose

from careloop.patients.energy import energy_proposal

FACTS = {
    "age_years": 40,
    "weight_kg": 70,
    "height_cm": 175,
    "pregnant": False,
    "breastfeeding": False,
    "dialysis": False,
}


def test_energy_range_uses_measured_weight_and_preserves_unknowns():
    estimate = energy_proposal(FACTS)
    assert estimate["action"]["amount"] == 1750
    assert estimate["action"]["upper"] == 2450
    assert estimate["inputs"]["weight_kg"] == 70
    assert estimate["method"] == "nice-cg32-1.4.2-v2"
    unknown = energy_proposal({**FACTS, "pregnant": None})
    assert "Clarify pregnant; its status is unknown." in unknown["review"]
    assert unknown["inputs"]["pregnant"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"age_years": None},
        {"weight_kg": None},
        {"height_cm": None},
        {"age_years": 17},
        {"pregnant": True},
        {"breastfeeding": True},
        {"dialysis": True},
    ],
)
def test_energy_requires_individual_assessment_or_missing_inputs(overrides):
    result = energy_proposal({**FACTS, **overrides})
    assert result["action"] is None
    assert result["issues"]


@pytest.mark.parametrize("weight, note", [(40, "refeeding"), (110, "may need to be lower")])
def test_energy_outside_bmi_range_shows_reference_with_review(weight, note):
    result = energy_proposal({**FACTS, "weight_kg": weight})
    assert result["action"]["amount"] == weight * 25
    assert result["action"]["upper"] == weight * 35
    assert result["calculation"]
    assert any(note in item for item in result["review"])
    assert not result["issues"]


@pytest.mark.parametrize("weight", [70, 110])
def test_energy_proposal_is_separate_until_clinician_adopts_and_approves(client, weight):
    p = patient(client, **{**FACTS, "weight_kg": weight})
    target = propose(client, p)
    estimate = target["body"]["energy_proposal"]
    assert estimate["action"]["amount"] == weight * 25
    assert target["body"]["items"] == []
    assert target["approved_revision"] is None
    response = client.post(
        f"/api/targets/{target['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "selected": [],
            "dispositions": [],
            "manual": [
                {
                    "action": {**estimate["action"], "amount": 1800, "upper": 2300},
                    "rationale": "Reviewed clinical suitability and activity; adjusted range.",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    edited = response.json()
    assert edited["body"]["energy_proposal"] == estimate
    assert edited["body"]["items"][0]["origin"] == "clinician"
    assert edited["body"]["items"][0]["action"]["amount"] == 1800
    assert edited["approved_revision"] is None
    assert approve(client, edited).status_code == 200
    changed = {**p["body"], "facts": {**p["body"]["facts"], "weight_kg": 72}}
    response = client.post(
        f"/api/patients/{p['id']}/revisions",
        json={
            **CLINICIAN,
            "expected_revision": 1,
            "body": changed,
        },
    )
    assert response.status_code == 201
    assert client.get(f"/api/targets/{target['id']}").json()["needs_review"]
    refreshed = propose(client, response.json())
    assert refreshed["body"]["energy_proposal"]["action"]["amount"] == 1800
    assert refreshed["approved_revision"] is None
