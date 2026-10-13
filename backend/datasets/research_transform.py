"""Normalize downloaded evidence into an isolated research staging database.

No live patient, knowledge, or approval journal is written. Research participants
are not clinical patients; recalls have no fabricated dates or approval coverage.
Missing nutrients remain null. Sources and native values accompany every record.
"""
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

from backend.datasets.paths import dataset_dir

ROOT = dataset_dir() / "research"
OUT = ROOT / "staged"
NUTRIENTS = {1008: "energy_kcal", 1003: "protein_g", 1093: "sodium_mg",
             1092: "potassium_mg", 1091: "phosphorus_mg", 1005: "carbs_g",
             1004: "fat_g", 1258: "sat_fat_g", 1079: "fiber_g", 2000: "sugar_g"}


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def encode(value):
    return json.dumps(clean(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ArticleTables(HTMLParser):
    """Keep source table cells verbatim, without guessing units or missing columns."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "research.sqlite3"
    temporary = OUT / "research.build.sqlite3"
    if temporary.exists():
        raise RuntimeError("unfinished staging build exists; inspect before retrying")
    records = json.loads((ROOT / "manifest.json").read_text())
    sources = {entry["path"]: entry for entry in records if entry["status"] == "downloaded"}
    conn = sqlite3.connect(temporary)
    conn.executescript("""
        CREATE TABLE source_files(path TEXT PRIMARY KEY, provenance_json TEXT NOT NULL);
        CREATE TABLE research_records(dataset TEXT, source_table TEXT, record_id TEXT,
            subject_id TEXT, document_json TEXT NOT NULL,
            PRIMARY KEY(dataset, source_table, record_id));
        CREATE TABLE patient_candidates(subject_id TEXT PRIMARY KEY, document_json TEXT NOT NULL);
        CREATE TABLE food_candidates(food_id TEXT PRIMARY KEY, document_json TEXT NOT NULL);
        CREATE TABLE rule_evidence(candidate_id TEXT PRIMARY KEY, document_json TEXT NOT NULL);
        CREATE INDEX research_subject ON research_records(dataset, subject_id);
    """)
    conn.executemany("INSERT INTO source_files VALUES (?,?)", [(key, encode(value)) for key, value in sources.items()])
    summary = {"database": str(target.relative_to(ROOT)), "counts": {}, "limitations": [
        "Research staging only: no live database writes, fabricated diagnoses, approvals or dates.",
        "NHANES is cross-sectional; dietary and laboratory survey weights require analytic design.",
        "MIMIC dates are de-identified; hospital records are not outpatient meal adherence.",
        "Food nutrients are per 100g where documented; no automatic portion/ingredient/category mapping.",
        "Rule evidence is not an executable or reviewed knowledge release.",
    ]}
    nhanes = {}
    for path in sorted((ROOT / "raw/nhanes").glob("*.xpt")):
        if str(path.relative_to(ROOT)) not in sources:
            continue
        frame = pd.read_sas(path, format="xport", encoding="utf-8")
        rows = [clean(row) for row in frame.to_dict(orient="records")]
        nhanes[path.stem] = rows
        conn.executemany("INSERT INTO research_records VALUES (?,?,?,?,?)", [
            ("NHANES_2021_2023", path.stem, str(index),
             f"NHANES-2021-2023-{int(row['SEQN'])}" if row.get("SEQN") is not None else None, encode(row))
            for index, row in enumerate(rows)])
        summary["counts"][path.stem] = len(rows)
    by_subject = {name: {int(row["SEQN"]): row for row in rows} for name, rows in nhanes.items()
                  if name not in {"DR1IFF_L", "DR2IFF_L"}}
    with (OUT / "patient_candidates.jsonl").open("w") as output:
        for demo in nhanes.get("DEMO_L", []):
            seqn = int(demo["SEQN"])
            subject = f"NHANES-2021-2023-{seqn}"
            body = by_subject.get("BMX_L", {}).get(seqn, {})
            bio = by_subject.get("BIOPRO_L", {}).get(seqn, {})
            a1c = by_subject.get("GHB_L", {}).get(seqn, {})
            document = {"research_subject_id": subject, "source": "NHANES_2021_2023",
                "clinical_import_allowed": False, "requires_review": True,
                "mapped_fields": {"age": demo.get("RIDAGEYR"),
                    "sex": {1: "M", 2: "F"}.get(demo.get("RIAGENDR")),
                    "weight_kg": body.get("BMXWT"), "height_cm": body.get("BMXHT"), "bmi": body.get("BMXBMI"),
                    "serum_K_meq_L": bio.get("LBXSKSI"), "serum_PO4_mg_dL": bio.get("LBXSPH"),
                    "hba1c_pct": a1c.get("LBXGH")},
                "unmapped_fields": ["diagnoses", "meds", "egfr", "longitudinal_labs", "clinical_dates", "approval"],
                "mapping_notes": ["Potassium mmol/L equals mEq/L for monovalent potassium.",
                    "Age may be top-coded; missing values remain null; laboratory sample starts at age 12."],
                "native_records": {name: values[seqn] for name, values in by_subject.items() if seqn in values}}
            output.write(encode(document) + "\n")
            conn.execute("INSERT INTO patient_candidates VALUES (?,?)", (subject, encode(document)))
    for archive in sorted((ROOT / "raw/usda").glob("*.zip")):
        if str(archive.relative_to(ROOT)) not in sources:
            continue
        count = 0
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.endswith(".json"):
                    continue
                document = json.loads(bundle.read(name))
                for foods in document.values():
                    if not isinstance(foods, list):
                        continue
                    for food in foods:
                        if not isinstance(food, dict) or "fdcId" not in food:
                            continue
                        nutrients = {key: None for key in NUTRIENTS.values()}
                        for nutrient in food.get("foodNutrients", []):
                            info = nutrient.get("nutrient", {})
                            nutrient_id = info.get("id")
                            if nutrient_id in NUTRIENTS:
                                expected = "kcal" if nutrient_id == 1008 else "mg" if nutrient_id in {1091,1092,1093} else "g"
                                if str(info.get("unitName", "")).lower() == expected:
                                    nutrients[NUTRIENTS[nutrient_id]] = nutrient.get("amount")
                        candidate = {"food_id": f"USDA-FDC-{food['fdcId']}", "name": food.get("description"),
                            "source_path": str(archive.relative_to(ROOT)), "source_member": name,
                            "nutrient_basis": "per_100_g", "nutrients": nutrients,
                            "missing_nutrients": [key for key, value in nutrients.items() if value is None],
                            "clinical_catalogue_import_allowed": False, "requires_review": True,
                            "native_record": food}
                        conn.execute("INSERT OR IGNORE INTO food_candidates VALUES (?,?)", (candidate["food_id"], encode(candidate)))
                        count += 1
        summary["counts"][archive.stem] = count
    mimic = ROOT / "raw/mimic/demo.zip"
    if str(mimic.relative_to(ROOT)) in sources:
        with zipfile.ZipFile(mimic) as bundle:
            for name in bundle.namelist():
                if not name.endswith((".csv", ".csv.gz")):
                    continue
                raw = bundle.read(name)
                if name.endswith(".gz"):
                    import gzip
                    raw = gzip.decompress(raw)
                rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
                conn.executemany("INSERT INTO research_records VALUES (?,?,?,?,?)", [
                    ("MIMIC_IV_DEMO_2_2", name, str(index),
                     "MIMIC-IV-DEMO-" + row["subject_id"] if row.get("subject_id") else None, encode(row))
                    for index, row in enumerate(rows)])
                summary["counts"][name] = len(rows)
    study = ROOT / "raw/singapore/meal_study.html"
    if str(study.relative_to(ROOT)) in sources:
        parser = ArticleTables()
        parser.feed(study.read_text())
        (OUT / "singapore_study_tables.json").write_text(encode({"source_path": str(study.relative_to(ROOT)),
            "requires_review": True, "tables": parser.tables}) + "\n")
        summary["counts"]["singapore_study_tables"] = len(parser.tables)
    pdf = ROOT / "raw/guidelines/kdigo_2024_ckd.pdf"
    if str(pdf.relative_to(ROOT)) in sources:
        text = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"]).decode()
        (OUT / "kdigo_2024_ckd.txt").write_text(text)
        with (OUT / "rule_evidence.jsonl").open("w") as output:
            for page, content in enumerate(text.split("\f"), start=1):
                for match in re.finditer(r"(?:Recommendation|Practice Point)\s+\d+(?:\.\d+)+[^\n]*", content):
                    if not any(term in content[max(0, match.start()-300):match.start()+1600].lower()
                               for term in ("protein", "sodium", "potassium", "phosph", "diet", "nutrition")):
                        continue
                    start = max(0, match.start() - 300)
                    candidate = {"candidate_id": f"KDIGO-2024-P{page}-{match.start()}",
                        "guideline": "KDIGO 2024 CKD", "pdf_page": page,
                        "source_path": str(pdf.relative_to(ROOT)), "source_sha256": sources[str(pdf.relative_to(ROOT))]["sha256"],
                        "source_url": sources[str(pdf.relative_to(ROOT))]["source_url"],
                        "extracted_heading": match.group(), "extracted_context": content[start:match.start()+2000],
                        "status": "UNREVIEWED_EVIDENCE", "executable_rule": None,
                        "required_review": ["Check original PDF including exceptions and evidence grades.",
                            "Map population and exclusions; determine hard ceiling versus soft aim.",
                            "Resolve conflicts against the entire rulebook before drafting executable actions."]}
                    output.write(encode(candidate) + "\n")
                    conn.execute("INSERT INTO rule_evidence VALUES (?,?)", (candidate["candidate_id"], encode(candidate)))
    for table in ("research_records", "patient_candidates", "food_candidates", "rule_evidence", "source_files"):
        summary["counts"][table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.commit()
    conn.close()
    temporary.replace(target)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
