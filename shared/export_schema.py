"""Generate the cross-language envelope schema from the canonical Python model.

Run ``python -m shared.export_schema`` to regenerate, or add ``--check`` in CI.
"""

import argparse
import json
from pathlib import Path

from shared.envelope_schema import NutrientEnvelope

SCHEMA_PATH = Path(__file__).with_name("envelope_schema.json")


def schema_text() -> str:
    schema = NutrientEnvelope.model_json_schema(by_alias=True, mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://careloop.local/schemas/envelope.schema.json"
    return json.dumps(schema, indent=2) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = schema_text()
    if args.check:
        if not SCHEMA_PATH.exists() or SCHEMA_PATH.read_text() != expected:
            parser.exit(1, "Envelope schema is stale: run python -m shared.export_schema\n")
    else:
        SCHEMA_PATH.write_text(expected)
