"""Population/selection regression checks for the reviewed condition rule builder."""

from uuid import UUID

import pytest

from careloop.evidence.condition_rules import build_rules
from careloop.patients.engine import evaluate, target_blockers


@pytest.fixture
def rules():
    # Minimal source anchors for builder tests; live publication separately verifies
    # full retained quotations and records the actual-source coverage matrix.
    texts = {
        "kdigo": "\n\n".join(
            [
                "Practice Point 3.3.1: Advise people with CKD",
                "Practice Point 3.3.2: Use renal dietitians",
                "Practice Point 3.3.1.4: Do not restrict protein",
                "Practice Point 3.3.1.3: Do not prescribe",
                "Recommendation 3.3.1.1: We suggest maintaining",
            ]
        ),
        "who": "Everyone older than 10 years of age should also aim\n\n"
        "Everyone older than 10 years of age should aim",
        "hpb": "<table><colgroup><col/><col/><col/><col/><col/><col/><col/><col/><col/></colgroup>",
        "rda": '<h3 id="RDC">\n\n<th>Iron</th>\n\ntbl32id2_0',
        "nkf-protein": "On the other hand, once a person has started",
        "nkf-potassium": "If you have high potassium (hyperkalemia)",
        "nkf-phosphorus": "Yes. Dialysis can remove some phosphorus",
        "nice-gout": "Explain to people with gout that there is not enough\n\n"
        "Advise people with gout that excess body weight",
    }
    plan = build_rules(
        {k: {"id": str(UUID(int=i)), "content": v} for i, (k, v) in enumerate(texts.items(), 1)}
    )
    return [{"rule_id": e["key"], "revision": 1, "body": e["body"]} for e in plan]


def results(rules, **changes):
    facts = {
        "age_years": 50,
        "weight_kg": 70,
        "has_ckd": False,
        "ckd_stage": None,
        "dialysis": False,
        "pregnant": False,
        "breastfeeding": False,
        "conditions": [],
    }
    return {r["rule_id"]: r for r in evaluate(rules, {**facts, **changes})}


@pytest.mark.parametrize("stage", ["G3a", "G3b", "G4", "G5"])
def test_adult_ckd_reference_is_stage_specific_and_weight_based(rules, stage):
    r = results(rules, has_ckd=True, ckd_stage=stage)
    active = [
        v for k, v in r.items() if k.startswith("ckd-protein-G") and v["status"] == "applicable"
    ]
    assert len(active) == 1
    assert active[0]["action"]["kind"] == "intake"
    assert active[0]["action"]["amount"] == pytest.approx(56)
    assert active[0]["action"]["unit"] == "g/day"
    assert r["ckd-protein-suitability"]["status"] == "needs_clinician"


def test_actual_adolescent_g2_scenario_has_growth_and_numeric_coverage(rules):
    r = results(
        rules,
        age_years=17,
        weight_kg=59.8,
        has_ckd=True,
        ckd_stage="G2",
        conditions=["History of single seizure (situation)", "Seizure disorder"],
    )
    assert r["ckd-child-growth"]["status"] == "needs_clinician"
    assert r["ckd-individual-nutrients"]["status"] == "needs_clinician"
    assert r["ckd-diet-quality"]["status"] == "advisory"
    assert r["adolescent-fibre"]["status"] == "applicable"
    assert r["adolescent-fruit_and_vegetables"]["status"] == "applicable"
    assert not any(
        v["status"] == "applicable" for k, v in r.items() if k.startswith("ckd-protein-G")
    )


@pytest.mark.parametrize(
    "changes",
    [{"age_years": 17.9}, {"dialysis": True}, {"pregnant": True}, {"breastfeeding": True}],
)
def test_adult_non_dialysis_protein_does_not_leak_to_other_populations(rules, changes):
    r = results(rules, has_ckd=True, ckd_stage="G3b", **changes)
    assert r["ckd-protein-G3b"]["status"] == "not_applicable"


def test_unknown_dialysis_does_not_establish_protein_eligibility(rules):
    r = results(rules, has_ckd=True, ckd_stage="G3a", dialysis=None)
    assert r["ckd-protein-G3a"]["status"] == "incomplete"
    assert r["ckd-protein-G3a"]["missing"] == ["dialysis"]


@pytest.mark.parametrize(
    "changes,prefix,count",
    [
        ({"conditions": ["Hypertension"]}, "hypertension-", 2),
        ({"conditions": ["Pre-Diabetes"]}, "prediabetes-", 2),
        ({"conditions": ["Type 2 Diabetes Mellitus"]}, "diabetes-", 2),
        (
            {"conditions": ["Type 2 Diabetes Mellitus at Risk of Hypoglycaemia"]},
            "hypoglycaemia-",
            3,
        ),
        ({"conditions": ["gout"]}, "gout-", 2),
        ({"pregnant": True}, "pregnancy-", 2),
        ({"breastfeeding": True}, "lactation-", 2),
        ({"dialysis": True}, "dialysis-", 3),
    ],
)
def test_condition_presence_activates_its_new_rules(rules, changes, prefix, count):
    r = results(rules, **changes)
    assert (
        sum(
            v["status"] in {"advisory", "needs_clinician", "applicable"}
            for k, v in r.items()
            if k.startswith(prefix)
        )
        == count
    )
    baseline = results(rules)
    assert all(v["status"] == "not_applicable" for k, v in baseline.items() if k.startswith(prefix))


def test_growth_assessment_cannot_be_silently_treated_as_optional_guidance(rules):
    r = results(rules, age_years=17, has_ckd=True, ckd_stage="G2")
    blockers = target_blockers(list(r.values()), [], [])
    assert any(b.get("rule_id") == "ckd-child-growth" for b in blockers)
    assert not any(b.get("rule_id") == "ckd-diet-quality" for b in blockers)


@pytest.mark.parametrize(
    "age,expected",
    [(10, "not_applicable"), (11, "applicable"), (17.9, "applicable"), (18, "excluded")],
)
def test_adolescent_scope_is_disjoint_from_adult_rules(rules, age, expected):
    assert results(rules, age_years=age)["adolescent-fibre"]["status"] == expected
