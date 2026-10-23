import pytest
from pydantic import ValidationError

from careloop.evidence.conflicts import overlap
from careloop.patients.engine import predicate
from careloop.patients.models import Facts


def test_ckd_status_preserves_unknown_and_legacy_stages():
    assert Facts().has_ckd is None
    assert Facts(has_ckd=False).ckd_stage is None
    assert Facts(has_ckd=True).ckd_stage is None
    assert Facts(ckd_stage="G4").has_ckd is True
    assert Facts(egfr=40).has_ckd is None
    with pytest.raises(ValidationError, match="CKD stage cannot be recorded"):
        Facts(has_ckd=False, ckd_stage="G1")
    with pytest.raises(ValidationError):
        Facts(has_ckd="false")


def test_no_ckd_does_not_require_stage_but_unknown_and_yes_do():
    stage = {"fact": "ckd_stage", "operator": "eq", "value": "G4"}
    assert predicate(stage, {"has_ckd": False}) == (False, [], [])
    assert predicate(stage, {}) == (None, ["ckd_stage"], [])
    assert predicate(stage, {"has_ckd": True}) == (None, ["ckd_stage"], [])
    status = {"fact": "has_ckd", "operator": "eq", "value": True}
    assert predicate(status, {"ckd_stage": "G1"}) == (True, [], [])
    assert predicate(status, {"has_ckd": False}) == (False, [], [])
    assert predicate(status, {}) == (None, ["has_ckd"], [])


def test_conflict_analysis_treats_stage_and_no_ckd_as_disjoint():
    stage = {
        "applicability": [{"fact": "ckd_stage", "operator": "eq", "value": "G4"}],
        "exceptions": [],
    }
    no_ckd = {
        "applicability": [{"fact": "has_ckd", "operator": "eq", "value": False}],
        "exceptions": [],
    }
    assert overlap(stage, no_ckd) is False
    assert overlap(stage, {"applicability": [], "exceptions": no_ckd["applicability"]}) is True
