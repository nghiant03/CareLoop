"""CareLoop backend application package.

Ensures the repository root is importable so the canonical schemas in
``shared/`` can be imported as ``shared.envelope_schema`` regardless of how the
app is launched (uvicorn, pytest, or ``python -m``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

__version__ = "0.1.0"
