import pytest

from careloop.patients.engine import predicate


@pytest.mark.parametrize(
    "condition,facts,expected",
    [
        ({"fact": "pregnant", "operator": "eq", "value": True}, {}, None),
        ({"fact": "pregnant", "operator": "eq", "value": True}, {"pregnant": False}, False),
        ({"fact": "conditions", "operator": "contains", "value": "ckd"}, {}, None),
        ({"fact": "conditions", "operator": "contains", "value": "ckd"}, {"conditions": []}, False),
        ({"fact": "age_years", "operator": "gte", "value": 18}, {"age_years": 18}, True),
        ({"fact": "age_years", "operator": "gte", "value": True}, {"age_years": 18}, None),
        ({"fact": "age_years", "operator": "gte", "value": "18"}, {"age_years": 18}, None),
        ({"fact": "unknown", "operator": "eq", "value": False}, {}, None),
    ],
)
def test_three_valued_predicates(condition, facts, expected):
    truth, missing, issues = predicate(condition, facts)
    assert truth is expected
    assert bool(missing or issues) == (expected is None)
