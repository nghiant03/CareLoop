"""Pin one explicitly selected knowledge release for the lifetime of a process."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import RLock

from backend.datasets.paths import dataset_path
from backend.knowledge.store import KnowledgeRelease, load_release
from backend.storage.postgres import database_url

_LOCK = RLock()
_CONFIG: tuple[str, str, str] | None = None
_RELEASE: KnowledgeRelease | None = None
_ROOT = Path(__file__).resolve().parents[2]


def selected_release() -> KnowledgeRelease | None:
    """Fixture mode is the development default; configured database mode fails closed.

    Any database/release setting requires both. Mode/configuration changes after
    first use require restart, preventing mixed process-wide rule/catalogue caches.
    Runtime connections are read-only and never bootstrap from repository JSON.
    """
    global _CONFIG, _RELEASE
    url = database_url("knowledge")
    database = url or ""
    release_id = os.environ.get("CARELOOP_KNOWLEDGE_RELEASE", "")
    mode = os.environ.get("CARELOOP_KNOWLEDGE_MODE") or ("database" if database or release_id else "fixtures")
    config = (mode, database, release_id)
    with _LOCK:
        if _CONFIG is not None:
            if config != _CONFIG:
                raise RuntimeError("Knowledge configuration changed after first use; restart the process")
            return _RELEASE
        if mode == "database":
            if not database or not release_id:
                raise ValueError("database knowledge mode requires a knowledge PostgreSQL URL and CARELOOP_KNOWLEDGE_RELEASE")
            candidate = load_release(database, release_id)
            from backend.knowledge.validation import validate_documents

            validate_documents(candidate.rules_document(), candidate.dishes())
            _RELEASE = candidate
        elif mode != "fixtures" or database or release_id:
            raise ValueError("knowledge mode must be fixtures without database settings, or database")
        _CONFIG = config
        return _RELEASE


def source_hashes() -> dict[str, str]:
    release = selected_release()
    if release is not None:
        return release.source_hashes()
    return {name: hashlib.sha256(dataset_path(Path(name).name).read_bytes()).hexdigest()
            for name in ("rules/rules.json", "data/dishes.json")}
