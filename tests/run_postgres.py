"""Run the suite against an isolated, temporary PostgreSQL server (no Docker)."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pgserver
import psycopg

root = Path("/tmp/opencode")
with TemporaryDirectory(prefix="careloop-check-", dir=root if root.exists() else None) as directory:
    server = pgserver.get_server(Path(directory) / "postgres", cleanup_mode="delete")
    try:
        url = server.get_uri()
        with psycopg.connect(url) as conn:
            print(conn.execute("SELECT version()").fetchone()[0], flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *sys.argv[1:]],
            env={**os.environ, "CARELOOP_TEST_DATABASE_URL": url},
        )
    finally:
        server.cleanup()
sys.exit(result.returncode)
