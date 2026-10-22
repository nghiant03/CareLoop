"""Export the canonical schema using wire aliases."""

import argparse
import json
from pathlib import Path

from shared.envelope_schema import NutrientEnvelope


def schema_text() -> str:
    schema = NutrientEnvelope.model_json_schema(by_alias=True, mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://careloop.local/schemas/envelope.schema.json"
    return json.dumps(schema, indent=2) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="explicit export destination; otherwise stdout")
    args = parser.parse_args()
    expected = schema_text()
    if args.output:
        args.output.write_text(expected, encoding="utf-8")
    else:
        print(expected, end="")
