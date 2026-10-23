import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from careloop.adapters import fndds, nhanes, sgfoodid
from careloop.foods.models import FoodInput
from careloop.foods.service import save_food
from careloop.patients.csv_import import export_csv, parse_csv
from careloop.patients.models import CSVInput
from careloop.patients.service import save_patient
from careloop.workflow import require_role

ADAPTERS = {"nhanes": nhanes, "fndds": fndds, "sgfoodid": sgfoodid}
MAX_DOWNLOAD_BYTES = 20_000_000


def acquire(source, directory, limit):
    if source not in ADAPTERS:
        raise ValueError("Unknown public data source")
    minimum, maximum = (1, 5000) if source == "nhanes" else (0, 10000)
    if not minimum <= limit <= maximum:
        raise ValueError(f"Limit must be {minimum}–{maximum}")
    adapter = ADAPTERS[source]
    directory = directory.expanduser().resolve()
    for parent in [Path.cwd(), *Path.cwd().parents]:
        if (parent / ".git").exists() and directory.is_relative_to(parent):
            raise ValueError("Raw data and artifacts must remain outside the repository")
    directory.mkdir(parents=True, exist_ok=True)
    paths, hashes = {}, {}
    for key, (url, suffix, signature) in adapter.SOURCES.items():
        with urlopen(url, timeout=60) as response:
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(payload) > MAX_DOWNLOAD_BYTES or not payload.lstrip().startswith(signature):
            raise ValueError(f"Unexpected or oversized {source}/{key} response")
        hashes[key] = hashlib.sha256(payload).hexdigest()
        paths[key] = directory / f"{key}-{hashes[key]}{suffix}"
        paths[key].write_bytes(payload)
    records, counts, details = adapter.read(paths, hashes, limit)
    if not records:
        raise ValueError("Source produced no eligible normalized records")
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if source == "nhanes":
        content, suffix = export_csv(records, adapter.NAMESPACE), ".csv"
    else:
        content = "".join(
            json.dumps(
                {
                    "namespace": adapter.NAMESPACE,
                    "external_id": code,
                    "body": body.model_dump(mode="json"),
                }
            )
            + "\n"
            for code, body in records
        )
        suffix = ".jsonl"
    output = directory / f"normalized-{identity}-{limit}{suffix}"
    output.write_text(content)
    manifest = {
        **details,
        "source": source,
        "sources": {k: spec[0] for k, spec in adapter.SOURCES.items()},
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": hashes,
        "raw_paths": {key: str(path) for key, path in paths.items()},
        "normalized_path": str(output),
        "normalized_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "limit": limit,
        "counts": counts,
    }
    path = directory / f"manifest-{identity}-{limit}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return records, manifest, path


def import_records(conn, source, records, actor, reason):
    """Import normalized records in the caller's transaction with explicit attribution."""
    if source == "nhanes":
        data = CSVInput(content=export_csv(records, nhanes.NAMESPACE), actor=actor, reason=reason)
        require_role(data, "clinician")
        return [save_patient(conn, record) for record in parse_csv(data)]
    if source not in ADAPTERS:
        raise ValueError("Unknown public data source")
    return [
        save_food(
            conn,
            FoodInput(
                namespace=ADAPTERS[source].NAMESPACE,
                external_id=code,
                body=body,
                actor=actor,
                reason=reason,
            ),
        )
        for code, body in records
    ]
