from __future__ import annotations

import os
from pathlib import Path

from backend.datasets.paths import dataset_dir


def artifact_dir(workflow: str) -> Path:
    """Generated outputs stay external. Published reports remain repository inputs."""
    root = Path(os.environ.get("CARELOOP_ARTIFACT_DIR") or dataset_dir() / "outputs").expanduser().resolve()
    checkout = Path(__file__).resolve().parents[1]
    if root == checkout or checkout in root.parents:
        raise ValueError("Artifact directory must be outside the code checkout")
    return root / workflow
