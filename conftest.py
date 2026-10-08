"""Repo-wide pytest bootstrap.

Milestone 3 moved the application stores into a single SQLite database whose
path is resolved lazily from ``CARELOOP_APP_DB``. To keep the whole test suite
hermetic, this conftest points that variable at a fresh temp file **at import
time** — before any test module (or conftest in a subdirectory) imports
backend application code — so tests never touch ``data/careloop_app.sqlite3``.

A root-level conftest covers every invocation shape:

* ``pytest rules backend evaluation`` (rootdir = repo root)
* ``pytest rules`` / ``pytest evaluation`` alone
* ``pytest backend`` (rootdir becomes ``backend/`` via
  ``backend/pyproject.toml`` — there this file is NOT collected, which is why
  ``backend/app/tests/conftest.py`` and ``backend/mining/conftest.py`` repeat
  the guards they need).

The path is also consumed lazily by ``backend.app.core.persistence``, so
setting the env var here is sufficient regardless of import order.
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