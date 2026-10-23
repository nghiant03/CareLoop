import math

from careloop.patients.models import Facts, PatientBody, Provenance

URL = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.xpt"
CODEBOOK = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.htm"
EDITION = "NHANES August 2021-August 2023 DEMO_L"
NAMESPACE = "nhanes:2021-2023:DEMO_L"
SOURCES = {"data": (URL, ".xpt", b"HEADER RECORD*******LIBRARY HEADER")}


def normalize(rows, checksum, limit):
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    identities = set()
    eligible = []
    counts = {"total": 0, "under_two": 0, "top_coded_age": 0, "missing_age": 0}
    for row in rows:
        counts["total"] += 1
        seqn, age = float(row["SEQN"]), float(row["RIDAGEYR"])
        if not math.isfinite(seqn) or not seqn.is_integer() or seqn <= 0 or seqn in identities:
            raise ValueError("DEMO_L contains an invalid or duplicate SEQN")
        identities.add(seqn)
        if math.isnan(age):
            counts["missing_age"] += 1
        elif not math.isfinite(age) or not 0 <= age <= 80:
            raise ValueError("DEMO_L contains an unexpected RIDAGEYR value")
        elif age < 2:
            # Filter before the integer check: XPORT can decode age 0 as a tiny float.
            counts["under_two"] += 1
        elif not age.is_integer():
            raise ValueError("DEMO_L contains a non-integer eligible RIDAGEYR value")
        elif age == 80:
            counts["top_coded_age"] += 1
        else:
            eligible.append((int(seqn), age))
    records = []
    for seqn, age in sorted(eligible)[:limit]:
        records.append(
            PatientBody(
                display_name=f"NHANES respondent {seqn}",
                facts=Facts(age_years=age),
                provenance=Provenance(
                    kind="public_dataset",
                    source=URL,
                    edition=EDITION,
                    record_id=str(seqn),
                    sha256=checksum,
                    notes="SEQN -> record identity; RIDAGEYR -> age_years at survey interview. "
                    "Exact interview date unavailable; observed_on is unknown. "
                    "Age 80 is top-coded and excluded. Diagnoses, reproductive status, "
                    "allergies, preferences, and clinical approvals are not inferred.",
                ),
            )
        )
    counts.update(
        eligible=len(eligible), selected=len(records), unselected=len(eligible) - len(records)
    )
    return records, counts


def read(paths, hashes, limit):
    import pandas as pd

    frame = pd.read_sas(paths["data"], format="xport")
    if not {"SEQN", "RIDAGEYR"} <= set(frame.columns):
        raise ValueError("DEMO_L is missing required columns")
    records, counts = normalize(
        frame[["SEQN", "RIDAGEYR"]].to_dict("records"), hashes["data"], limit
    )
    if not records:
        raise ValueError("No eligible participant records found")
    details = {
        "codebook": CODEBOOK,
        "edition": EDITION,
        "adapter": "demo-l-age-v1",
        "pandas_version": pd.__version__,
        "selection": "Age 2-79 inclusive; lowest SEQN first up to limit; not representative",
        "columns_available": list(frame.columns),
        "fields_mapped": {"SEQN": "external_id", "RIDAGEYR": "facts.age_years"},
        "unknown_fields": [name for name in Facts.model_fields if name != "age_years"],
    }
    return records, counts, details
