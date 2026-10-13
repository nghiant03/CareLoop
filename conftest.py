"""Select an isolated application database before test modules import app code.

Runtime databases contain clinical state and must not be used by tests.
Backend-only pytest roots may not load this file; backend fixtures supply their
own isolation guard for that invocation.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TMP_DB_DIR = tempfile.mkdtemp(prefix="careloop-pytest-")
os.environ["CARELOOP_APP_DB"] = str(Path(_TMP_DB_DIR) / "careloop_app.sqlite3")
atexit.register(shutil.rmtree, _TMP_DB_DIR, ignore_errors=True)
