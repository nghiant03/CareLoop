"""Reproducible public-food retrieval pilot, distinct from clinical plan evaluation."""

import argparse
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path
from time import perf_counter

from careloop.foods.clustering import fit, retrieve
from careloop.foods.models import FoodBody


def evaluate(rows, clusters=4, top=5):
    started = perf_counter()
    model = fit(rows, clusters)
    fit_seconds = perf_counter() - started
    results = {}
    for method in ("cluster", "nearest", "same_category"):
        started = perf_counter()
        queries, exposed = [], set()
        for source in rows:
            found = retrieve(rows, source, model, method)[:top]
            exposed.update(str(row["id"]) for row, _ in found)
            known = [distance for _, distance in found if distance is not None]
            queries.append(
                {
                    "food_id": str(source["id"]),
                    "returned_ids": [str(row["id"]) for row, _ in found],
                    "same_category": sum(
                        row["body"]["category"] == source["body"]["category"] for row, _ in found
                    ),
                    "known_distances": known,
                }
            )
        returned = sum(len(q["returned_ids"]) for q in queries)
        distances = [value for q in queries for value in q["known_distances"]]
        results[method] = {
            "queries": len(queries),
            "queries_with_results": sum(bool(q["returned_ids"]) for q in queries),
            "returned": returned,
            "distinct_recommended_foods": len(exposed),
            "same_category_fraction": sum(q["same_category"] for q in queries) / returned
            if returned
            else None,
            "mean_known_distance": sum(distances) / len(distances) if distances else None,
            "missing_distance_count": returned - len(distances),
            "retrieval_seconds": perf_counter() - started,
            "query_results": queries,
        }
    return {
        "schema_version": 1,
        "scope": "transductive public-food retrieval pilot",
        "selection_size": len(rows),
        "top": top,
        "model": model,
        "cluster_sizes": dict(Counter(model["membership"].values())),
        "fit_seconds": fit_seconds,
        "methods": results,
        "limitations": [
            "Categories are a compatibility proxy, not suitability labels",
            "Queries are included when fitting this transductive catalogue model",
            "No patient, allergy, approved-target or portion checks in this pilot",
            "Same-category baseline ranks by source identity, not nutrient distance",
            "Runtime depends on hardware; this is not the full evaluation",
        ],
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="careloop-data food JSONL export")
    parser.add_argument(
        "--output", type=Path, required=True, help="Explicit JSON report destination"
    )
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    if not 2 <= args.limit <= 1000 or not 1 <= args.clusters <= 8 or not 1 <= args.top <= 20:
        parser.error("Use limit 2–1000, clusters 1–8, top 1–20")
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must not overwrite the input")
    payload = args.input.read_bytes()
    rows = []
    identities = set()
    for line in payload.splitlines():
        record = json.loads(line)
        identity = record["namespace"] + ":" + record["external_id"]
        if identity in identities:
            parser.error("Duplicate food source identity")
        identities.add(identity)
        body = FoodBody.model_validate(record["body"]).model_dump(mode="json")
        rows.append({"id": identity, "body": body})
    # Hash ordering is fixed and avoids selecting by nutrition/category or source order.
    selected = sorted(rows, key=lambda row: hashlib.sha256(row["id"].encode()).hexdigest())[
        : args.limit
    ]
    if len(selected) < 2:
        parser.error("At least two food records are required")
    report = evaluate(selected, args.clusters, args.top)
    report.update(
        input_sha256=hashlib.sha256(payload).hexdigest(),
        source_records=len(rows),
        selection="First limit source identities ordered by SHA-256(identity)",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "report": str(args.output),
                "selected": len(selected),
                "feature_exclusions": len(report["model"]["excluded_food_ids"]),
                "methods": {
                    key: {k: v for k, v in value.items() if k != "query_results"}
                    for key, value in report["methods"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
