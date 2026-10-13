"""Resolve writable locations without creating files or importing application state."""

from __future__ import annotations

import os
from pathlib import Path


def default_app_db_path() -> Path:
    """Use the user's state directory, independent of the installed source tree."""
    configured = os.environ.get("XDG_STATE_HOME")
    state_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    if not state_home.is_absolute():
        raise ValueError("XDG_STATE_HOME must be an absolute path")
    return state_home / "careloop" / "careloop_app.sqlite3"


def artifact_dir(workflow: str) -> Path:
    """Resolve run outputs under CARELOOP_ARTIFACT_DIR or ./artifacts.

    Published reports remain repository inputs; callers create output directories
    only when writing. Deployments should configure an absolute external root.
    """
    return Path(os.environ.get("CARELOOP_ARTIFACT_DIR") or "artifacts").expanduser().resolve() / workflow
