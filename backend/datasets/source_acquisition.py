import concurrent.futures
import gzip
import hashlib
import json
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime

from backend.datasets.paths import dataset_dir

ROOT = dataset_dir() / "research"
SOURCES = {
    **{f"nhanes/{name}.{ext}": f"https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/{name}.{ext}"
       for name in ("DEMO_L", "BMX_L", "DR1IFF_L", "DR2IFF_L", "DR1TOT_L", "DR2TOT_L", "BIOPRO_L", "ALB_CR_L", "GHB_L",
                    "BPXO_L", "BPQ_L", "DIQ_L", "KIQ_U_L", "RXQ_RX_L")
       for ext in ("xpt", "htm")},
    "healthbench/consensus.jsonl": "https://openaipublic.blob.core.windows.net/simple-evals/healthbench/consensus_2025-05-09-20-00-46.jsonl",
    "guidelines/kdigo_2024_ckd.pdf": "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf",
    "guidelines/kdigo_2022_diabetes_ckd.pdf": "https://kdigo.org/wp-content/uploads/2022/10/KDIGO-2022-Clinical-Practice-Guideline-for-Diabetes-Management-in-CKD.pdf",
    "guidelines/ada_kdigo_2022_consensus.pdf": "https://kdigo.org/wp-content/uploads/2018/03/ADA-KDIGO-Consensus-Report-Diabetes-CKD-Diabetes-Care-2022.pdf",
    "guidelines/kdigo_2017_ckd_mbd.pdf": "https://kdigo.org/wp-content/uploads/2017/02/2017-KDIGO-CKD-MBD-GL-Update.pdf",
    "guidelines/nhlbi_dash.pdf": "https://www.nhlbi.nih.gov/files/docs/public/heart/new_dash.pdf",
    "guidelines/kdoqi_2020_nutrition_ckd.html": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8054797/",
    "guidelines/ada_mnt_consensus.html": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6540072/",
    "guidelines/openfda_drug_labels.json": (
        "https://api.fda.gov/drug/label.json?search=openfda.generic_name:"
        "(spironolactone+OR+lisinopril+OR+losartan+OR+furosemide+OR+hydrochlorothiazide"
        "+OR+metformin+OR+empagliflozin+OR+warfarin+OR+sevelamer)&limit=20"
    ),
    "guidelines/fda_lasix_label.pdf": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/016273s066lbl.pdf",
    "guidelines/fda_coumadin_label.pdf": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/009218s017lbl.pdf",
    "singapore/sgfoodid_202607.zip": "https://www.kaggle.com/api/v1/datasets/download/adisongoh/comprehensive-food-nutritional-information",
    "singapore/meal_study.html": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8304763/",
    "usda/download_index.html": "https://fdc.nal.usda.gov/download-datasets/",
    "mimic/demo.zip": "https://physionet.org/static/published-projects/mimic-iv-demo/mimic-iv-clinical-database-demo-2.2.zip",
    **{f"eicu/{name}.csv.gz": f"https://physionet.org/files/eicu-crd-demo/2.0.1/{name}.csv.gz"
       for name in ("patient", "lab", "medication", "diagnosis", "pastHistory")},
    "uci/diabetes_130_us_hospitals.zip": "https://archive.ics.uci.edu/static/public/296/diabetes+130-us+hospitals+for+years+1999-2008.zip",
    "uci/chronic_kidney_disease.zip": "https://www.kaggle.com/api/v1/datasets/download/mansoordaku/ckdisease",
}


def _fetch_range(url: str, start: int, end: int) -> bytes:
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "CareLoop-research-source-acquisition/1.0",
                    "Range": f"bytes={start}-{end}",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                expected = end - start + 1
                if len(data) == expected:
                    return data
        except Exception:
            if attempt == 3:
                raise
    raise ValueError(f"Incomplete byte range {start}-{end} for {url}")


def download(item):
    name, url = item
    target = ROOT / "raw" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"path": str(target.relative_to(ROOT)), "source_url": url,
              "retrieved_at": datetime.now(UTC).isoformat()}
    try:
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "CareLoop-research-source-acquisition/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                record["final_url"] = response.url
                record["content_type"] = response.headers.get("Content-Type")
                content_len_hdr = response.headers.get("Content-Length")
                expected_len = int(content_len_hdr) if content_len_hdr and content_len_hdr.isdigit() else None
                accept_ranges = (response.headers.get("Accept-Ranges") or "").lower() == "bytes"
                final_url = response.url
                if accept_ranges and expected_len and expected_len > 2_000_000:
                    pass
                else:
                    with temporary.open("wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
            if accept_ranges and expected_len and expected_len > 2_000_000 and not temporary.exists():
                chunk_size = 1024 * 1024
                ranges = [
                    (offset, min(offset + chunk_size - 1, expected_len - 1))
                    for offset in range(0, expected_len, chunk_size)
                ]
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as rpool:
                    parts = list(rpool.map(lambda r: _fetch_range(final_url, r[0], r[1]), ranges))
                with temporary.open("wb") as output:
                    for part in parts:
                        output.write(part)
            if expected_len is not None and temporary.stat().st_size != expected_len:
                raise ValueError(f"truncated download: got {temporary.stat().st_size} of {expected_len} bytes")
            signature = temporary.open("rb").read(256)
            if target.suffix == ".xpt" and not signature.startswith(b"HEADER RECORD"):
                raise ValueError("response is not SAS transport data")
            if target.suffix == ".pdf" and not signature.startswith(b"%PDF"):
                raise ValueError("response is not PDF")
            if target.suffix == ".zip":
                if not signature.startswith(b"PK"):
                    raise ValueError("response is not ZIP")
                with zipfile.ZipFile(temporary) as zf:
                    if zf.testzip() is not None:
                        raise ValueError("corrupted ZIP archive")
            if target.suffix == ".gz":
                if not signature.startswith(b"\x1f\x8b"):
                    raise ValueError("response is not GZIP")
                with gzip.open(temporary, "rb") as gf:
                    while gf.read(1024 * 1024):
                        pass
            if target.suffix in (".jsonl", ".json") and not signature.lstrip().startswith(b"{"):
                raise ValueError("response is not JSON")
            temporary.rename(target)
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        record.update(status="downloaded", bytes=target.stat().st_size, sha256=digest.hexdigest())
    except Exception as exc:  # noqa: BLE001
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
                link = max(choices)
                selected["usda/" + category + ".zip"] = urllib.parse.urljoin(SOURCES["usda/download_index.html"], link)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            records.extend(pool.map(download, selected.items()))
    (ROOT / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
