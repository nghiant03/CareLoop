import pytest

from careloop.evidence.conflicts import overlap
from careloop.patients.conditions import condition_matches
from careloop.patients.engine import predicate


@pytest.mark.parametrize(
    "recorded,rule",
    [
        ("Prediabetes", "Pre-Diabetes"),
        ("  PRE–DIABETES  ", "Prediabetes"),
        ("Prediabetes (disorder)", "Pre-Diabetes"),
        ("hypertension", "Hypertension"),
        ("HTN", "Hypertension"),
        ("Essential (primary) hypertension", "Hypertension"),
        ("Unspecified essential hypertension", "Hypertension"),
        ("T2DM", "Type 2 Diabetes Mellitus"),
        ("Type II diabetes", "Type 2 Diabetes Mellitus"),
        ("Type 2 diabetes mellitus with unspecified complications", "Type 2 Diabetes Mellitus"),
        (
            "Type 2 Diabetes Mellitus at Risk of Hypoglycemia",
            "Type 2 Diabetes Mellitus at Risk of Hypoglycaemia",
        ),
        ("Type 2 Diabetes Mellitus at Risk of Hypoglycaemia", "Type 2 Diabetes Mellitus"),
        ("Sodium–wasting nephropathy", "sodium-wasting nephropathy"),
    ],
)
def test_equivalent_labels_and_explicit_subtypes_match(recorded, rule):
    facts = {"conditions": [recorded]}
    assert predicate({"fact": "conditions", "operator": "contains", "value": rule}, facts) == (
        True,
        [],
        [],
    )
    assert facts["conditions"] == [recorded]


@pytest.mark.parametrize(
    "recorded,rule",
    [
        ("Diabetes (type unspecified)", "Type 2 Diabetes Mellitus"),
        ("Type 1 Diabetes Mellitus", "Type 2 Diabetes Mellitus"),
        ("Prediabetes", "Type 2 Diabetes Mellitus"),
        ("Gestational diabetes", "Type 2 Diabetes Mellitus"),
        ("Portal hypertension", "Hypertension"),
        ("Pulmonary hypertension", "Hypertension"),
        ("No hypertension", "Hypertension"),
        ("Family history of hypertension", "Hypertension"),
        ("History of hypertension", "Hypertension"),
        ("Hypertension", "Essential hypertension"),
        ("Type 2 Diabetes Mellitus", "Type 2 Diabetes Mellitus at Risk of Hypoglycaemia"),
        ("Type 2 Diabetes Mellitus", "Type 2 diabetes mellitus with unspecified complications"),
    ],
)
def test_distinct_diagnoses_history_and_negation_are_not_fuzzy_equated(recorded, rule):
    assert not condition_matches(recorded, rule)


def test_unknown_empty_and_non_condition_facts_keep_their_meaning():
    p = {"fact": "conditions", "operator": "contains", "value": "Pre-Diabetes"}
    assert predicate(p, {"conditions": None}) == (None, ["conditions"], [])
    assert predicate(p, {"conditions": []}) == (False, [], [])
    assert predicate({**p, "fact": "allergies", "value": "milk"}, {"allergies": ["Milk"]}) == (
        False,
        [],
        [],
    )


@pytest.mark.parametrize(
    "required,excluded,expected",
    [
        ("Prediabetes", "Pre-Diabetes", False),
        ("Essential hypertension", "Hypertension", False),
        ("Hypertension", "Essential hypertension", True),
        ("Type 1 diabetes mellitus", "Type 2 diabetes mellitus", True),
    ],
)
def test_conflict_overlap_uses_same_alias_and_subtype_semantics(required, excluded, expected):
    def body(field, value):
        return {
            "applicability": [],
            "exceptions": [],
            field: [{"fact": "conditions", "operator": "contains", "value": value}],
        }

    assert overlap(body("applicability", required), body("exceptions", excluded)) is expected


def test_old_exact_match_approval_is_not_ready_after_alias_expands_applicability(
    client, monkeypatch
):
    from test_patients import approve, patient, propose, rule, with_energy

    from careloop.patients import engine

    rule(client)
    rule(
        client,
        subject="fibre",
        unit="g/day",
        kind="minimum",
        amount=25,
        applicability=[{"fact": "conditions", "operator": "contains", "value": "Pre-Diabetes"}],
    )
    p = patient(client, conditions=["Prediabetes"])
    with monkeypatch.context() as old:
        old.setattr(engine, "condition_matches", lambda actual, expected: actual == expected)
        target = with_energy(client, propose(client, p))
        assert approve(client, target).status_code == 200
        assert client.get(f"/api/patients/{p['id']}/target-readiness").json()["targets_ready"]
    ready = client.get(f"/api/patients/{p['id']}/target-readiness").json()
    assert ready["targets_ready"] is False
    assert ready["approved_target"] is None
    fresh = propose(client, p)
    assert len(fresh["body"]["items"]) == 2
    assert client.get(f"/api/patients/{p['id']}").json()["body"]["facts"]["conditions"] == [
        "Prediabetes"
    ]
