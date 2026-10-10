"""Ensure the repo root is importable regardless of pytest rootdir config.

The repository-root ``pyproject.toml`` sets ``pythonpath = ["."]`` and the
editable ``careloop`` install adds the repo root via a ``.pth`` file, so
``backend.mining`` normally imports from anywhere. This conftest keeps that
guarantee if pytest runs without either (e.g., no install, foreign rootdir).
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)