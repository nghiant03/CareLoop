"""Copy a SQLite snapshot to external storage without overwriting either database."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from backend.storage_paths import default_app_db_path


def copy_database(source: Path, destination: Path) -> Path:
    """Back up SQLite, including WAL data, and publish a verified copy exclusively.

    Stop application writers before migration and switch their configuration only
    after success. The source is opened read-only and retained for rollback.
    Existing destinations (including symlinks) are never overwritten. This is a
    snapshot copy, not a continuous replication or schema-migration operation.
    """
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".careloop-backup-", dir=destination.parent)
    os.close(fd)
    staging = Path(temporary)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(staging)) as copied:
                original.backup(copied)
                if copied.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Copied database failed SQLite integrity_check")
        with staging.open("rb") as snapshot:
            os.fsync(snapshot.fileno())
        # Linking within one directory publishes atomically and refuses races.
        os.link(staging, destination)
    finally:
        staging.unlink(missing_ok=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", type=Path,
                        help="defaults to CARELOOP_APP_DB or the user's state directory")
    args = parser.parse_args(argv)
    destination = args.destination
    if destination is None:
        configured = os.environ.get("CARELOOP_APP_DB")
        destination = Path(configured) if configured else default_app_db_path()
    try:
        copied = copy_database(args.source, destination)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Migration failed: {exc}\n")
    print(f"Copied database to {copied}; source retained. Set CARELOOP_APP_DB={copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
