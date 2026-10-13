"""Resolve external datasets without creating files or consulting checkout seeds."""

import os
from pathlib import Path


def dataset_dir() -> Path:
    """Use CARELOOP_DATASET_DIR or the user's XDG data directory.

    Dataset directories must be outside the code checkout. Missing datasets do
    not trigger downloads or fall back to bundled/synthetic replacements.
    """
    configured = os.environ.get("CARELOOP_DATASET_DIR")
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
    root = Path(configured).expanduser() if configured else data_home / "careloop/datasets"
    if not root.is_absolute():
        raise ValueError("CARELOOP_DATASET_DIR and XDG_DATA_HOME must be absolute")
    root = root.resolve()
    checkout = Path(__file__).resolve().parents[2]
    if root == checkout or checkout in root.parents:
        raise ValueError("Dataset directory must be outside the code checkout")
    return root


def dataset_path(name: str) -> Path:
    """Resolve a fixture by filename; persisted provenance labels stay unchanged."""
    if name not in {"patients.json", "dishes.json", "rules.json", "example_trace.json"}:
        raise ValueError(f"Unknown fixture dataset: {name}")
    return dataset_dir() / "fixtures" / name
