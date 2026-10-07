"""Ensure the repo root is importable regardless of pytest rootdir config.

``backend/pyproject.toml`` sets ``pythonpath = ["."]`` relative to its own
directory, which would put ``backend/`` (not the repo root) on sys.path when
pytest picks it as the config file. This conftest pins the repo root so
``backend.mining`` imports work when run from anywhere.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)