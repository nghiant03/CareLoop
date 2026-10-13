"""Resolve writable locations without creating files or importing application state."""

from __future__ import annotations

import os
from pathlib import Path
from backend.datasets.paths import dataset_dir


def default_app_db_path() -> Path:
    """Use the user's state directory, independent of the installed source tree."""
    configured = os.environ.get("XDG_STATE_HOME")
    state_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    if not state_home.is_absolute():
        raise ValueError("XDG_STATE_HOME must be an absolute path")
    return state_home / "careloop" / "careloop_app.sqlite3"


def artifact_dir(workflow: str) -> Path:
    """Resolve run outputs under CARELOOP_ARTIFACT_DIR or external datasets/outputs.

    Published reports remain repository inputs; callers create output directories
    only when writing. Deployments should configure an absolute external root.
    """
    root = Path(os.environ.get("CARELOOP_ARTIFACT_DIR") or dataset_dir() / "outputs").expanduser().resolve()
    checkout = Path(__file__).resolve().parents[1]
    if root == checkout or checkout in root.parents:
        raise ValueError("Artifact directory must be outside the code checkout")
    return root / workflow
