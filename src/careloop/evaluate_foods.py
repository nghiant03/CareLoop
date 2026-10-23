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


def evaluate_export(path: Path, limit=300, clusters=4, top=5):
    """Return a reproducible report from a normalized food export."""
    if not 2 <= limit <= 1000 or not 1 <= clusters <= 8 or not 1 <= top <= 20:
        raise ValueError("Use limit 2–1000, clusters 1–8, top 1–20")
    payload = path.read_bytes()
    rows = []
    identities = set()
    for line in payload.splitlines():
        record = json.loads(line)
        identity = record["namespace"] + ":" + record["external_id"]
        if identity in identities:
            raise ValueError("Duplicate food source identity")
        identities.add(identity)
        body = FoodBody.model_validate(record["body"]).model_dump(mode="json")
        rows.append({"id": identity, "body": body})
    # Hash before taking the limit so source ordering does not determine the sample.
    selected = sorted(rows, key=lambda row: hashlib.sha256(row["id"].encode()).hexdigest())[:limit]
    if len(selected) < 2:
        raise ValueError("At least two food records are required")
    report = evaluate(selected, clusters, top)
    report.update(
        input_sha256=hashlib.sha256(payload).hexdigest(),
        source_records=len(rows),
        selection="First limit source identities ordered by SHA-256(identity)",
    )
    return report
