"""Explicit command orchestration; adapters do not write application databases."""

import argparse
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from careloop.adapters import nhanes
from careloop.db import database_url
from careloop.foods.models import FoodInput
from careloop.foods.service import save_food
from careloop.ingestion import ADAPTERS, acquire
from careloop.patients.csv_import import export_csv, parse_csv
from careloop.patients.models import CSVInput
from careloop.patients.service import save_patient


def import_records(source, records, actor):
    """One application transaction; duplicate source identities roll back the batch."""
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        if source == "nhanes":
            data = CSVInput(
                content=export_csv(records, nhanes.NAMESPACE),
                actor={"name": actor, "role": "clinician"},
                reason="Import public survey records for academic demonstration",
            )
            for record in parse_csv(data):
                save_patient(conn, record)
        else:
            for code, body in records:
                save_food(
                    conn,
                    FoodInput(
                        namespace=ADAPTERS[source].NAMESPACE,
                        external_id=code,
                        body=body,
                        actor={"name": actor, "role": "reviewer"},
                        reason=f"Import public composition from {source}",
                    ),
                )


def main():
    parser = argparse.ArgumentParser(description="Acquire public data through source adapters")
    parser.add_argument("source", choices=ADAPTERS)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--import-records", action="store_true")
    parser.add_argument("--actor", default="Public data importer")
    args = parser.parse_args()
    maximum = 5000 if args.source == "nhanes" else 10000
    minimum = 1 if args.source == "nhanes" else 0
    if not minimum <= args.limit <= maximum:
        parser.error(f"--limit must be {minimum}–{maximum}; zero means all food records")
    version = "kaggle-v1" if args.source == "sgfoodid" else "2021-2023"
    directory = (
        args.directory or Path.home() / ".local/share/careloop/public" / args.source / version
    )
    records, manifest, path = acquire(args.source, directory, args.limit)
    if args.import_records:
        import_records(args.source, records, args.actor)
    print(
        json.dumps(
            {"manifest": str(path), "imported": args.import_records, **manifest["counts"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
