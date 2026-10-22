import json
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from shared.envelope_schema import NutrientConstraint, NutrientEnvelope, NutrientKind
from shared.export_schema import schema_text


def test_export_is_derived_from_the_serialization_model():
    schema = json.loads(schema_text())
    Draft202012Validator.check_schema(schema)
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id") == "https://careloop.local/schemas/envelope.schema.json"
    assert schema == NutrientEnvelope.model_json_schema(by_alias=True, mode="serialization")


def test_cli_defaults_to_stdout_without_creating_files(tmp_path):
    result = subprocess.run([sys.executable, "-m", "shared.export_schema"],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == json.loads(schema_text())
    assert not list(tmp_path.iterdir())


def test_cli_exports_to_an_explicit_destination(tmp_path):
    output = tmp_path / "export.json"
    subprocess.run([sys.executable, "-m", "shared.export_schema", "--output", str(output)],
                   cwd=tmp_path, capture_output=True, text=True, check=True)
    assert output.read_text() == schema_text()


@pytest.mark.parametrize("nutrient", list(NutrientKind))
@pytest.mark.parametrize("unit", ["kcal", "g", "mg", "litres"])
def test_generated_constraint_schema_preserves_unit_validation(nutrient, unit):
    target = {"nutrient": nutrient.value, "kind": "max", "value": 1, "unit": unit}
    canonical = "kcal" if nutrient == NutrientKind.ENERGY_KCAL else "mg" if nutrient.value.endswith("_mg") else "g"
    schema = NutrientConstraint.model_json_schema(by_alias=True, mode="serialization")
    errors = list(Draft202012Validator(schema).iter_errors(target))
    assert bool(errors) == (unit != canonical)
    if unit == canonical:
        NutrientConstraint.model_validate(target)
    else:
        with pytest.raises(ValidationError):
            NutrientConstraint.model_validate(target)
