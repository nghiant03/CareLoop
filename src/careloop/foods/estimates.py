"""Explicit, reproducible missing-value estimates for the SG FoodID demo catalogue."""

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from collections import Counter
from copy import deepcopy
from pathlib import Path
from statistics import median

from careloop.adapters.sgfoodid import MAPPING, NAMESPACE, number
from careloop.evidence.diet_rules import ACTOR
from careloop.foods.models import FoodBody

VERSION = "sgfoodid-estimates-v1"
METADATA_KEY = "careloop_estimates"
FIELDS = ("fibre", "sodium", "trans_fat", "total_sugars")
WHO = "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"


def estimate_details(food):
    try:
        data = json.loads(food.get("source_details", {}).get(METADATA_KEY, "{}"))
    except (ValueError, TypeError):
        return {}
    return data.get("estimates", {}) if isinstance(data, dict) else {}


def restore_source(body):
    """Restore numeric source cells only; trace/missing and implausible fat stay unknown."""
    restored, rejected = {}, {}
    for field in FIELDS:
        if body["nutrients"].get(field) is not None:
            continue
        column = MAPPING[field] + " - Per 100"
        raw = body.get("source_details", {}).get(column, "-")
        try:
            value = number(raw)
        except ValueError:
            rejected[field] = {"raw": raw, "reason": "Unparseable source value"}
            continue
        if value is None:
            continue
        value = float(value)
        fat = body["nutrients"].get("fat")
        if field == "trans_fat" and fat is not None and value > fat:
            rejected[field] = {"raw": raw, "reason": "Source trans fat exceeds total fat"}
            continue
        body["nutrients"][field] = value
        restored[field] = {"value": value, "column": column, "raw": raw}
    return restored, rejected


def cohort_value(rows, food, field):
    basis = food.get("basis", "g")
    category = food["category"]
    group = category.split(" / ")[0]
    for scope in ("subcategory", "food_group", "same_basis_catalogue"):
        donors = []
        for row in rows:
            other = row["body"]
            value = other["nutrients"].get(field)
            if (
                other.get("basis", "g") != basis
                or value is None
                or field in estimate_details(other)
            ):
                continue
            if scope == "subcategory" and other["category"] != category:
                continue
            if scope == "food_group" and other["category"].split(" / ")[0] != group:
                continue
            if field == "trans_fat" and other["nutrients"].get("fat") is not None:
                if value > other["nutrients"]["fat"]:
                    continue
            donors.append((str(row["id"]), value))
        if len(donors) >= 3:
            value = round(median(v for _, v in donors), 4)
            fat = food["nutrients"].get("fat")
            if field == "trans_fat" and fat is not None:
                value = min(value, fat)
            return value, {
                "value": value,
                "method": "cohort_median",
                "scope": scope,
                "category": category if scope == "subcategory" else group,
                "basis": basis,
                "donor_count": len(donors),
                "donor_ids_sha256": hashlib.sha256(json.dumps(sorted(donors)).encode()).hexdigest(),
                "confidence": "low",
                "range": [min(v for _, v in donors), max(v for _, v in donors)],
            }
    return None, None


def prepare(rows):
    """Never change existing values or use this run's estimates as donor measurements."""
    originals = {str(row["id"]): row for row in rows}
    cohort = deepcopy([r for r in rows if r.get("namespace") == NAMESPACE])
    repairs = {}
    for row in cohort:
        repairs[str(row["id"])] = restore_source(row["body"])
    plans = []
    for row in cohort:
        food = deepcopy(row["body"])
        identity = str(row["id"])
        estimates = dict(estimate_details(food))
        restored, rejected = repairs[identity]
        for field in FIELDS:
            if food["nutrients"].get(field) is None:
                value, method = cohort_value(cohort, food, field)
                if method:
                    food["nutrients"][field] = value
                    estimates[field] = method
        if food["nutrients"].get("free_sugars") is None:
            total = food["nutrients"].get("total_sugars")
            if total is not None:
                # Total sugars is an upper-bound proxy, not an equivalent measurement.
                food["nutrients"]["free_sugars"] = total
                estimates["free_sugars"] = {
                    "value": total,
                    "method": "total_sugars_upper_bound_proxy",
                    "source_field": "total_sugars",
                    "source_is_estimated": "total_sugars" in estimates,
                    "confidence": "low" if "total_sugars" in estimates else "conservative_proxy",
                    "note": "Includes intrinsic sugars; may reject otherwise suitable foods. "
                    "An imputed total is not a guaranteed upper bound.",
                    "definition_source": WHO,
                }
        if food.get("food_groups", {}).get("fruit_and_vegetables") is None:
            # Do not guess recipe fractions or convert ml to grams. Mixed/processed
            # foods receive zero credit, not a claim that they contain no vegetables.
            whole = food.get("basis", "g") == "g" and food["category"] in {
                "Fruit / Fresh fruit",
                "Vegetables / Non-leafy vegetables",
                "Vegetables / Leafy vegetables",
                "Vegetables / Mushrooms and fungi",
            }
            value = 100 if whole else 0
            food.setdefault("food_groups", {})["fruit_and_vegetables"] = value
            estimates["fruit_and_vegetables"] = {
                "value": value,
                "method": "whole_produce_category_credit"
                if whole
                else "unverified_recipe_zero_credit",
                "category": food["category"],
                "confidence": "category_estimate" if whole else "conservative_credit",
                "note": "Estimated edible contribution per 100 g; mixed foods, juices and "
                "starchy roots receive no credit without recipe evidence.",
            }
        if food == originals[identity]["body"]:
            continue
        previous = json.loads(food.get("source_details", {}).get(METADATA_KEY, "{}"))
        metadata = {
            "version": VERSION,
            "estimates": estimates,
            "source_restorations": {**previous.get("source_restorations", {}), **restored},
            "rejected_source_values": {**previous.get("rejected_source_values", {}), **rejected},
        }
        food.setdefault("source_details", {})[METADATA_KEY] = json.dumps(metadata, sort_keys=True)
        note = (
            "User-authorized demo estimates (" + VERSION + "): missing nutrients use "
            "same-basis food-category medians; free sugars use total sugars as a conservative "
            "proxy; fruit/vegetable credit is category-estimated. These are not measured "
            "values or verified clinical composition. Methods and original source cells "
            "are retained in source_details.careloop_estimates."
        )
        if note not in (food.get("review_note") or ""):
            food["review_note"] = ((food.get("review_note") or "") + "\n" + note).strip()
        food = FoodBody.model_validate(food).model_dump(mode="json")
        plans.append(
            {
                "food_id": identity,
                "expected_revision": row["latest_revision"],
                "name": food["name"],
                "body": food,
            }
        )
    return plans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def api(path, payload=None):
        request = urllib.request.Request(
            args.api.rstrip("/") + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    rows = []
    while True:
        page = api(f"/foods?limit=100&offset={len(rows)}")
        rows.extend(page)
        if len(page) < 100:
            break
    # Keep the original audit snapshot on resumed/idempotent runs.
    before = args.output / "foods-before.json"
    if not before.exists():
        before.write_text(json.dumps(rows, indent=2))
    plan = prepare(rows)
    if plan or not (args.output / "plan.json").exists():
        (args.output / "plan.json").write_text(json.dumps(plan, indent=2))
    summary = Counter(field for entry in plan for field in estimate_details(entry["body"]))
    print(f"Prepared {len(plan)} food revisions: {dict(summary)}", flush=True)
    if not args.apply:
        return
    for entry in plan:
        result = api(
            f"/foods/{entry['food_id']}/revisions",
            {
                "actor": ACTOR,
                "reason": "User explicitly requested labelled general estimates "
                "for missing food composition; preserve source observations "
                "and derivation methods.",
                "expected_revision": entry["expected_revision"],
                "body": entry["body"],
            },
        )
        if result["body"] != entry["body"]:
            raise RuntimeError(f"Read-back mismatch for {entry['food_id']}")
        with (args.output / "events.jsonl").open("a") as log:
            log.write(
                json.dumps({"food_id": result["id"], "revision": result["latest_revision"]}) + "\n"
            )
    print(f"Applied and verified {len(plan)} food revisions.")


if __name__ == "__main__":
    main()
