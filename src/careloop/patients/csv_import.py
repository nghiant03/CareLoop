"""Strict create-only CSV import: validate all rows before any database write."""

import csv
import io
import json

from pydantic import ValidationError

from careloop.patients.models import PatientInput
from careloop.workflow import WorkflowError

COLUMNS = ["display_name", "external_namespace", "external_id", "facts_json", "provenance_json"]


def export_csv(records, namespace):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "display_name": record.display_name,
                "external_namespace": namespace,
                "external_id": record.provenance.record_id,
                "facts_json": record.facts.model_dump_json(),
                "provenance_json": record.provenance.model_dump_json(),
            }
        )
    return output.getvalue()


def parse_csv(data):
    reader = csv.DictReader(io.StringIO(data.content), strict=True)
    try:
        columns = reader.fieldnames
    except csv.Error as exc:
        raise WorkflowError(422, "Invalid CSV header") from exc
    if columns != COLUMNS:
        raise WorkflowError(422, "CSV columns must be: " + ",".join(COLUMNS))
    patients = []
    identities = set()
    try:
        for line, row in enumerate(reader, 2):
            if len(patients) >= 5000:
                raise WorkflowError(422, "CSV exceeds 5000 rows")
            if None in row or any(value is None for value in row.values()):
                raise WorkflowError(422, f"CSV row {line}: wrong number of columns")
            patient = PatientInput.model_validate(
                {
                    "actor": data.actor,
                    "reason": data.reason,
                    "external_namespace": row["external_namespace"] or None,
                    "external_id": row["external_id"] or None,
                    "body": {
                        "display_name": row["display_name"],
                        "facts": json.loads(row["facts_json"]),
                        "provenance": json.loads(row["provenance_json"]),
                    },
                }
            )
            identity = (patient.external_namespace, patient.external_id)
            if identity[0] is not None:
                if identity in identities:
                    raise WorkflowError(422, f"CSV row {line}: duplicate external identity")
                identities.add(identity)
            patients.append(patient)
    except (ValueError, ValidationError, csv.Error) as exc:
        raise WorkflowError(422, f"Invalid CSV near line {reader.line_num}: {exc}") from exc
    if not patients:
        raise WorkflowError(422, "CSV contains no patient records")
    return patients
