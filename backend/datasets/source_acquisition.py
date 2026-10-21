"""Download public research sources; retain failures and SHA-256 provenance.

Local staging only. Never writes clinical state, approves rules, or uses credentials.
"""
import concurrent.futures
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.datasets.paths import dataset_dir

ROOT = dataset_dir() / "research"
SOURCES = {
    # BPXO/BPQ/DIQ/KIQ_U/RXQ_RX provide the hypertension, diabetes, dialysis and
    # medication inputs used by the external rule-engine evaluation.
    **{f"nhanes/{name}.{ext}": f"https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/{name}.{ext}"
       for name in ("DEMO_L", "BMX_L", "DR1IFF_L", "DR2IFF_L", "DR1TOT_L", "DR2TOT_L", "BIOPRO_L", "ALB_CR_L", "GHB_L",
                    "BPXO_L", "BPQ_L", "DIQ_L", "KIQ_U_L", "RXQ_RX_L")
       for ext in ("xpt", "htm")},
    # Physician-consensus HealthBench conversations (MIT licence), used only for
    # escalation/refusal evaluation; rubric grading needs a separate grader.
    "healthbench/consensus.jsonl": "https://openaipublic.blob.core.windows.net/simple-evals/healthbench/consensus_2025-05-09-20-00-46.jsonl",
    "guidelines/kdigo_2024_ckd.pdf": "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf",
    "guidelines/kdigo_index.html": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
    "singapore/meal_study.html": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8304763/",
    "singapore/sgfoodid.html": "https://www.hpb.gov.sg/healthy-living/food-and-beverage/sgfoodid/",
    "usda/download_index.html": "https://fdc.nal.usda.gov/download-datasets/",
    "mimic/demo_index.html": "https://physionet.org/content/mimic-iv-demo/2.2/",
    "mimic/demo.zip": "https://physionet.org/static/published-projects/mimic-iv-demo/mimic-iv-clinical-database-demo-2.2.zip",
    # eICU-CRD demo 2.0.1 (open access, ~2,500 ICU stays): a second longitudinal
    # lab/medication source that cross-validates trend thresholds from MIMIC demo.
    "eicu/demo_index.html": "https://physionet.org/content/eicu-crd-demo/2.0.1/",
    **{f"eicu/{name}.csv.gz": f"https://physionet.org/files/eicu-crd-demo/2.0.1/{name}.csv.gz"
       for name in ("patient", "lab", "medication", "diagnosis", "pastHistory")},
    # UCI ML repository: real hospital encounters with medications and A1c at
    # scale (medication-rule coverage), plus a small cross-sectional CKD cohort
    # as an independent check on NHANES-derived rule-engine concordance.
    "uci/diabetes_130_us_hospitals.zip": "https://archive.ics.uci.edu/static/public/296/diabetes+130-us+hospitals+for+years+1999-2008.zip",
    "uci/chronic_kidney_disease.zip": "https://archive.ics.uci.edu/static/public/336/chronic+kidney+disease.zip",
}

def download(item):
    name, url = item
    target = ROOT / "raw" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"path": str(target.relative_to(ROOT)), "source_url": url,
              "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "CareLoop-research-source-acquisition/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                record["final_url"] = response.url
                record["content_type"] = response.headers.get("Content-Type")
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            signature = temporary.open("rb").read(256)
            if target.suffix == ".xpt" and not signature.startswith(b"HEADER RECORD"):
                raise ValueError("response is not SAS transport data")
            if target.suffix == ".pdf" and not signature.startswith(b"%PDF"):
                raise ValueError("response is not PDF")
            if target.suffix == ".zip" and not signature.startswith(b"PK"):
                raise ValueError("response is not ZIP")
            if target.suffix == ".jsonl" and not signature.lstrip().startswith(b"{"):
                raise ValueError("response is not JSON Lines")
            temporary.rename(target)
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        record.update(status="downloaded", bytes=target.stat().st_size, sha256=digest.hexdigest())
    except Exception as exc:
        record.update(status="unavailable", error=str(exc))
        temporary = target.with_suffix(target.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
    print(name, record["status"], flush=True)
    return record

if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        records = list(pool.map(download, SOURCES.items()))
    index = ROOT / "raw/usda/download_index.html"
    if index.exists():
        links = re.findall(r'(?:href=["\x27])([^"\x27]+\.zip)', index.read_text(errors="replace"))
        selected = {}
        for category in ("foundation_food", "survey_food"):
            choices = [link for link in links if category in link.lower() and "json" in link.lower()]
            if choices:
                link = sorted(choices)[-1]
                selected["usda/" + category + ".zip"] = urllib.parse.urljoin(SOURCES["usda/download_index.html"], link)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            records.extend(pool.map(download, selected.items()))
    (ROOT / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
