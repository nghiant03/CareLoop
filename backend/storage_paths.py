"""Resolve writable locations without creating files or importing application state."""

from __future__ import annotations

import os
from pathlib import Path

from backend.datasets.paths import dataset_dir


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
