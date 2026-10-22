"""Translate local FNDDS workbooks into food composition and edible portions."""

import math
from collections import defaultdict
from urllib.parse import quote

from careloop.foods.models import FoodBody, Nutrients, Portion
from careloop.patients.models import Provenance

BASE = "https://www.ars.usda.gov/ARSUserFiles/80400530/apps/"
FILES = {
    "nutrients": "2021-2023 FNDDS At A Glance - FNDDS Nutrient Values.xlsx",
    "portions": "2021-2023 FNDDS At A Glance - Portions and Weights.xlsx",
}
MAPPING = {
    "energy": "Energy (kcal)",
    "protein": "Protein (g)",
    "carbohydrate": "Carbohydrate (g)",
    "fat": "Total Fat (g)",
    "saturated_fat": "Fatty acids, total saturated (g)",
    "fibre": "Fiber, total dietary (g)",
    "total_sugars": "Sugars, total\n(g)",
    "sodium": "Sodium (mg)",
    "potassium": "Potassium (mg)",
    "phosphorus": "Phosphorus (mg)",
}
NAMESPACE = "fndds:2021-2023"
SOURCES = {key: (BASE + quote(name), ".xlsx", b"PK") for key, name in FILES.items()}


def food_code(value):
    number = float(value)
    if (
        not math.isfinite(number)
        or not number.is_integer()
        or not 10_000_000 <= number <= 99_999_999
    ):
        raise ValueError("Invalid FNDDS food code")
    return str(int(number))


def normalize(nutrient_rows, portion_rows, hashes, limit):
    portions = defaultdict(list)
    omitted = 0
    for row in portion_rows:
        code = food_code(row["Food code"])
        grams = float(row["Portion weight\n(g)"])
        if not math.isfinite(grams) or not 0 < grams <= 10000:
            omitted += 1
            continue
        seq = float(row["Seq num"])
        if not seq.is_integer() or seq <= 0:
            raise ValueError("Invalid FNDDS portion sequence")
        portions[code].append(
            Portion(id=f"seq_{int(seq)}", label=str(row["Portion description"]), grams=grams)
        )
    bodies, seen = [], set()
    for row in sorted(nutrient_rows, key=lambda r: food_code(r["Food code"])):
        code = food_code(row["Food code"])
        if code in seen:
            raise ValueError("Duplicate FNDDS food code")
        seen.add(code)
        nutrients = {}
        for key, column in MAPPING.items():
            value = row[column]
            nutrients[key] = None if value is None or math.isnan(float(value)) else float(value)
        body = FoodBody(
            name=str(row["Main food description"]),
            category=str(row["WWEIA Category description"]),
            nutrients=Nutrients(**nutrients),
            portions=portions[code],
            provenance=Provenance(
                kind="public_dataset",
                source=BASE + quote(FILES["nutrients"]),
                edition="FNDDS 2021-2023",
                record_id=code,
                sha256=hashes["nutrients"],
                notes="Per 100 g edible portion; kcal, g, and mg as mapped. "
                "Portions source: "
                + BASE
                + quote(FILES["portions"])
                + "; SHA-256 "
                + hashes["portions"]
                + ". Free sugars, ingredients and safety classifications are unknown. "
                "Planning portions and slots require explicit reviewer annotation.",
            ),
        )
        bodies.append((code, body))
    selected = bodies[:limit] if limit else bodies
    return selected, {
        "source_foods": len(bodies),
        "selected_foods": len(selected),
        "omitted_nonpositive_missing_or_oversized_portions": omitted,
        "source_portions": len(portion_rows),
        "selected_portions": sum(len(body.portions) for _, body in selected),
        "unknown_nutrient_counts": {
            key: sum(getattr(body.nutrients, key) is None for _, body in selected)
            for key in Nutrients.model_fields
        },
    }


def read(paths, hashes, limit):
    import pandas as pd

    descriptions = pd.read_excel(paths["nutrients"], sheet_name="Variable Descriptions")
    if not any("per 100 g edible portion" in str(value) for value in descriptions.to_numpy().flat):
        raise ValueError("Nutrient basis is not the expected 100 g edible portion")
    nutrients = pd.read_excel(paths["nutrients"], sheet_name="FNDDS Nutrient Values", header=1)
    portions = pd.read_excel(paths["portions"], sheet_name="Portions and Weights", header=1)
    required = {
        "Food code",
        "Main food description",
        "WWEIA Category description",
        *MAPPING.values(),
    }
    if not required <= set(nutrients.columns) or not {
        "Food code",
        "Seq num",
        "Portion description",
        "Portion weight\n(g)",
    } <= set(portions.columns):
        raise ValueError("FNDDS workbook columns changed")
    records, counts = normalize(
        nutrients.to_dict("records"), portions.to_dict("records"), hashes, limit
    )
    details = {
        "adapter": "fndds-composition-v1",
        "selection": "Ascending food code, first limit records; 0 means all; "
        "not SEA representative",
        "field_mapping": MAPPING,
        "pandas_version": pd.__version__,
    }
    return records, counts, details
