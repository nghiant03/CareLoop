"""Content-addressed inputs and resumable, single-attempt experiment records."""

import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".local/share/careloop/public/evaluation/system-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def freeze(path, value):
    """Never replace an existing frozen experiment with different inputs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    except FileExistsError:
        if read(path) != value:
            raise ValueError(f"Frozen inputs differ: {path}; prepare a new experiment") from None
    return value


def now():
    return datetime.now(UTC).isoformat()


def environment():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "processor": platform.processor(),
    }


def code_hashes():
    base = Path(__file__).resolve().parents[1]
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*.py"))
    }


def claim(path, metadata):
    """Pending records are retained on interruption; resume never repeats a call."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as stream:
            json.dump({**metadata, "state": "pending", "started_at": now()}, stream, indent=2)
    except FileExistsError:
        return False
    return True
