"""Provision local-only ignored credentials without replacing existing secrets.

Compose file-backed secrets preserve host permissions. Files are readable by
non-root container users (0444) inside a private host directory (0700).
Local administrators and anyone with Docker access can read them regardless.
"""

import os
import secrets
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / ".secrets"
DIRECTORY.mkdir(mode=0o700, exist_ok=True)
if DIRECTORY.is_symlink():
    raise SystemExit("Refusing symlinked secrets directory")
DIRECTORY.chmod(0o700)


def provision(name, value=None):
    path = DIRECTORY / name
    if path.is_symlink():
        raise SystemExit(f"Refusing symlinked secret: {name}")
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write((value if value is not None else secrets.token_hex(32)) + "\n")
    existing = path.read_text().strip()
    if not existing or "\n" in existing:
        raise SystemExit(f"Invalid secret file: {name}")
    if value is not None and existing != value:
        raise SystemExit(f"Existing {name} differs; refusing credential replacement")
    path.chmod(0o444)
    return existing


admin = provision("postgres_admin_password")
app = provision("postgres_app_password")
reader = provision("postgres_knowledge_reader_password")
operator = provision("postgres_knowledge_operator_password")
for name, user, password, database in (
    ("clinical_admin_url", "careloop_admin", admin, "careloop_clinical"),
    ("knowledge_admin_url", "careloop_admin", admin, "careloop_knowledge"),
    ("clinical_app_url", "careloop_app", app, "careloop_clinical"),
    ("knowledge_reader_url", "careloop_knowledge_reader", reader, "careloop_knowledge"),
    ("knowledge_operator_url", "careloop_knowledge_operator", operator, "careloop_knowledge"),
):
    base = f"postgresql://{user}:{quote(password, safe='')}@"
    provision(name, base + f"postgres:5432/{database}")
    provision(name + "_local", base + f"127.0.0.1:5433/{database}")

# Bind-mounted operator workspace must be provisioned, not accidentally created
# root-owned by Docker. It contains unpublished exports, never clinical records.
from backend.datasets.paths import dataset_dir

workspace = dataset_dir() / "outputs/knowledge"
workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
# The Compose tool container runs as the invoking host user for this bind mount.
print("Private secrets prepared without replacement; no credentials displayed.")
print("For operator export access, set CARELOOP_OPERATOR_UID/GID to your host uid/gid.")
