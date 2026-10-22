"""Translate the user's Kaggle SG FoodID snapshot; preserve units and qualifiers."""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from decimal import Decimal

from careloop.foods.models import FoodBody, Nutrients, Portion
from careloop.patients.models import Provenance

DATASET = "adisongoh/comprehensive-food-nutritional-information"
URL = f"https://www.kaggle.com/datasets/{DATASET}"
NAMESPACE = "sgfoodid:kaggle:adisongoh:v1"
MEMBER = "food_nutrition_sgfoodid_combined_202607.csv"
SOURCES = {
    "archive": (
        f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}?datasetVersionNumber=1",
        ".zip",
        b"PK",
    ),
    "metadata": (f"https://www.kaggle.com/api/v1/datasets/view/{DATASET}", ".json", b"{"),
}
MAPPING = {
    "energy": "Energy (kcal)",
    "protein": "Protein (g)",
    "fat": "Total Fat (g)",
    "saturated_fat": "Saturated Fat (g)",
    "carbohydrate": "Carbohydrate (g)",
    "total_sugars": "Sugar (g)",
    "added_sugars": "Added Sugar (g)",
    "fibre": "Dietary Fibre (g)",
    "sodium": "Sodium (mg)",
    "potassium": "Potassium (mg)",
    "phosphorus": "Phosphorus (mg)",
}


def number(value):
    if value in {"", "-", "Trace"}:
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError(f"Unsupported SG FoodID numeric value: {value!r}")
    return Decimal(value)


def serving(text, basis, edible):
    match = re.search(r"=\s*(\d+(?:\.\d+)?)\s*(g|ml)$", text)
    if match is None or match[2] != basis:
        raise ValueError(f"Unrecognized or mismatched serving units: {text!r}")
    quantity = Decimal(match[1]) * edible
    if not 0 < quantity <= 10000:
        raise ValueError("Serving outside supported quantity range")
    return quantity


def serving_check(row, quantity, edible):
    """Compare to independently supplied serving values, allowing displayed rounding.

    This is a source-consistency check, not independent food-chemistry validation.
    """
    mismatches = []
    compared = 0
    for nutrient, column in MAPPING.items():
        per100, per_serving = row[column + " - Per 100"], row[column + " - Per Serving"]
        a, b = number(per100), number(per_serving)
        if a is None or b is None:
            continue
        compared += 1
        reconstructed = a * quantity / 100
        # Half a displayed unit for each rounded nutrient value. Include the
        # displayed edible-percentage and whole-unit serving measurement rounding.
        rounding = Decimal(10) ** a.as_tuple().exponent / 2 * quantity / 100
        rounding += Decimal(10) ** b.as_tuple().exponent / 2
        percent = Decimal(row["Edible Portion"][:-1])
        rounding += a * quantity / edible / 100 * (Decimal(10) ** percent.as_tuple().exponent / 200)
        rounding += a / 100 * edible / 2
        if abs(reconstructed - b) > rounding:
            mismatches.append(
                f"Serving discrepancy for {nutrient}: source {b}; computed {reconstructed}"
            )
    return compared, mismatches


def normalize(rows, checksum, limit):
    records, names = [], set()
    bases, qualifiers = Counter(), Counter()
    comparisons = mismatches = 0
    for row in rows:
        name = row["Food Name"].strip()
        if not name or name in names:
            raise ValueError("Missing or duplicate SG FoodID food name")
        names.add(name)
        basis = {"Per 100g": "g", "Per 100ml": "ml"}.get(row["Per 100 Unit"])
        if basis is None:
            raise ValueError("Unknown SG FoodID nutrient basis")
        bases[basis] += 1
        if not re.fullmatch(r"\d+(?:\.\d+)?%", row["Edible Portion"]):
            raise ValueError("Unknown edible percentage")
        edible = Decimal(row["Edible Portion"][:-1]) / 100
        if not 0 < edible <= 1:
            raise ValueError("Invalid edible percentage")
        nutrients = {}
        for key, column in MAPPING.items():
            raw = row[column + " - Per 100"]
            value = number(raw)
            if value is None:
                qualifiers[raw or "empty"] += 1
            nutrients[key] = float(value) if value is not None else None
        default_quantity = serving(row["Default Serving Size"], basis, edible)
        portions = []
        warnings = []
        labels = [row["Default Serving Size"]]
        if row["Alternative Serving Size(s)"] not in {"", "-"}:
            labels += re.split(r",\s*(?=\d)", row["Alternative Serving Size(s)"])
        for index, label in enumerate(labels):
            try:
                quantity = serving(label, basis, edible)
            except ValueError as exc:
                warnings.append(str(exc))
                continue
            portions.append(
                Portion(
                    id=f"serving_{index}",
                    label=label,
                    **{"grams" if basis == "g" else "millilitres": float(quantity)},
                )
            )
        compared, differences = serving_check(row, default_quantity, edible)
        comparisons += compared
        mismatches += len(differences)
        warnings.extend(differences)
        # The mirror exposes names, not official source IDs; retain that distinction.
        identity = hashlib.sha256(name.encode()).hexdigest()
        body = FoodBody(
            name=name,
            category=row["Food Group"] + " / " + row["Food Subgroup"],
            basis=basis,
            nutrients=Nutrients(**nutrients),
            portions=portions,
            source_details=dict(row),
            import_warnings=warnings,
            provenance=Provenance(
                kind="public_dataset",
                source=URL,
                edition="Kaggle SG FoodID mirror version 1 (July 2026)",
                record_id=identity,
                sha256=checksum,
                notes="Uploader attributes this snapshot to SG FoodID. "
                "Identity is a hash of the mirror's unique food name, not an official HPB ID. "
                "Nutrients retain the source per-100 g/ml basis. Portion quantities are edible "
                "amounts: displayed serving amount times edible percentage. Trace and missing "
                "values stay unknown. Added sugar is not free sugar. Raw row retained in "
                "source_details; safety and meal suitability are not inferred.",
            ),
        )
        records.append((identity, body))
    selected = records[:limit] if limit else records
    return selected, {
        "source_foods": len(records),
        "selected_foods": len(selected),
        "basis_counts": dict(bases),
        "unknown_qualifier_counts": dict(qualifiers),
        "serving_comparisons": comparisons,
        "serving_discrepancies": mismatches,
        "selected_portions": sum(len(body.portions) for _, body in selected),
        "unknown_nutrient_counts": {
            key: sum(getattr(body.nutrients, key) is None for _, body in selected)
            for key in Nutrients.model_fields
        },
    }


def read(paths, hashes, limit):
    metadata = json.loads(paths["metadata"].read_text())
    if metadata.get("currentVersionNumber") != 1:
        raise ValueError("Mirror metadata version changed; review the pinned version-1 adapter")
    with zipfile.ZipFile(paths["archive"]) as archive:
        info = archive.getinfo(MEMBER)
        if info.file_size > 5_000_000:
            raise ValueError("SG FoodID CSV exceeds the bounded snapshot size")
        content = archive.read(MEMBER).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    required = {
        "Food Name",
        "Food Group",
        "Food Subgroup",
        "Per 100 Unit",
        "Edible Portion",
        "Default Serving Size",
        "Alternative Serving Size(s)",
    }
    required |= {
        column + suffix
        for column in MAPPING.values()
        for suffix in (" - Per 100", " - Per Serving")
    }
    if not required <= set(reader.fieldnames or []):
        raise ValueError("SG FoodID CSV columns changed")
    records, counts = normalize(list(reader), hashes["archive"], limit)
    return (
        records,
        counts,
        {
            "adapter": "sgfoodid-kaggle-v1",
            "dataset_version": 1,
            "uploader": metadata.get("ownerRef"),
            "uploader_declared_license": metadata.get("licenseName"),
            "dataset_updated": metadata.get("lastUpdated"),
            "field_mapping": MAPPING,
            "selection": "Source CSV order, first limit records; 0 means all",
            "source_attribution": metadata.get("description"),
            "serving_check": "Per-100 value × edible serving quantity / 100 "
            "versus supplied per-serving value; "
            "allowance for displayed nutrient, edible percentage, and quantity rounding",
        },
    )
