import pytest

from careloop.adapters.nhanes import NAMESPACE, normalize
from careloop.patients.csv_import import export_csv, parse_csv
from careloop.patients.models import CSVInput


def test_public_data_mapping_preserves_unknowns_and_excludes_top_coding():
    records, counts = normalize(
        [
            {"SEQN": 1, "RIDAGEYR": 5.397605346934028e-79},
            {"SEQN": 2, "RIDAGEYR": 80},
            {"SEQN": 4, "RIDAGEYR": 60},
            {"SEQN": 3, "RIDAGEYR": 2},
            {"SEQN": 5, "RIDAGEYR": float("nan")},
        ],
        "a" * 64,
        1,
    )
    assert counts == {
        "total": 5,
        "under_two": 1,
        "top_coded_age": 1,
        "missing_age": 1,
        "eligible": 2,
        "selected": 1,
        "unselected": 1,
    }
    parsed = parse_csv(
        CSVInput(
            content=export_csv(records, NAMESPACE),
            actor={"name": "Test", "role": "clinician"},
            reason="Test import",
        )
    )
    assert parsed[0].external_id == "3"
    assert parsed[0].body.facts.age_years == 2
    assert parsed[0].body.facts.conditions is None
    assert parsed[0].body.facts.allergies is None
    assert parsed[0].body.facts.observed_on is None
    assert parsed[0].body.provenance.sha256 == "a" * 64


@pytest.mark.parametrize(
    "rows",
    [
        [{"SEQN": 1, "RIDAGEYR": 30}, {"SEQN": 1, "RIDAGEYR": 40}],
        [{"SEQN": 1, "RIDAGEYR": 81}],
        [{"SEQN": 1, "RIDAGEYR": 30.5}],
        [{"SEQN": float("nan"), "RIDAGEYR": 30}],
    ],
)
def test_invalid_dataset_identity_or_age_fails(rows):
    with pytest.raises(ValueError):
        normalize(rows, "a" * 64, 100)
