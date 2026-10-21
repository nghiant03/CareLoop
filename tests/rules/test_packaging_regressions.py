"""Code-only distributions and external-dataset smoke checks; never install packages.

Building requires existing Hatchling tooling. CARELOOP_BUILD_PYTHONPATH can name
available tool directories, including an unpacked local cache, without installation.
The smoke process uses the existing runtime dependencies but imports CareLoop only
from the extracted wheel, outside the checkout with its editable root removed.
"""

import json
import os
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = {"rules/engine.py", "shared/envelope_schema.py", "backend/datasets/paths.py"}


def test_resource_selection_is_explicit_and_state_is_excluded():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]
    assert set(config["targets"]["wheel"]["only-include"]) == {
        "backend", "shared", "rules",
    }
    assert {"**/*.sqlite3", "**/*-wal", "**/*-shm"} <= set(config["exclude"])


@pytest.fixture
def distributions(tmp_path):
    """Build with available tooling into isolated temporary output, or report a skip."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = os.environ.get("CARELOOP_BUILD_PYTHONPATH", "")
    probe = subprocess.run([sys.executable, "-c", "import hatchling.build"],
                           cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    if probe.returncode:
        pytest.skip("Hatchling build tooling unavailable; no dependencies installed: " + probe.stderr.strip())
    script = """
import json, sys
from hatchling.build import build_wheel, build_sdist
print(json.dumps([build_wheel(sys.argv[1]), build_sdist(sys.argv[1])]))
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    wheel, sdist = json.loads(result.stdout.strip().splitlines()[-1])
    return tmp_path / wheel, tmp_path / sdist


def assert_no_application_state(members):
    for member in members:
        name = Path(member).name.lower()
        assert not any(marker in name for marker in (".sqlite", ".db")), member
        assert not name.endswith(("-wal", "-shm")), member
        assert "__pycache__" not in member, member


def test_wheel_and_sdist_keep_resources_without_clinical_state(distributions):
    wheel, sdist = distributions
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
    assert RESOURCES <= set(members)
    assert "shared/envelope_schema.json" not in members
    assert not any(name.startswith(("data/", "dataset/", "datasets/")) for name in members)
    assert not any(name.endswith((".json", ".jsonl", ".csv", ".xpt", ".pdf", ".parquet")) for name in members)
    assert_no_application_state(members)
    with tarfile.open(sdist) as archive:
        members = [member.name.split("/", 1)[-1] for member in archive.getmembers()]
    assert RESOURCES <= set(members)
    assert "shared/envelope_schema.json" not in members
    assert not any(name.startswith(("data/", "dataset/", "datasets/")) for name in members)
    assert not any(name.endswith((".json", ".jsonl", ".csv", ".xpt", ".pdf", ".parquet")) for name in members)
    assert_no_application_state(members)


def test_out_of_checkout_wheel_loads_rules_patients_dishes_and_kb(distributions, tmp_path, pg_databases):
    wheel, _ = distributions
    installed = tmp_path / "wheel-root"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    work = tmp_path / "outside-checkout"
    work.mkdir()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CARELOOP_APP_DATABASE_URL=pg_databases["clinical"])
    from backend.datasets.paths import dataset_dir
    env["CARELOOP_DATASET_DIR"] = str(dataset_dir())
    env.pop("PYTHONPATH", None)
    script = """
import json, sys
from pathlib import Path
installed, checkout = map(Path, sys.argv[1:])
# Retain the current environment's dependencies, not its editable source root.
sys.path[:] = [entry for entry in sys.path if Path(entry or '.').resolve() != checkout]
sys.path.insert(0, str(installed))
from rules import engine
from shared import envelope_schema
from backend.optim import real_data
from backend.app.api.patients import get_patient
from backend.app.api.rules import run_rules_service
from backend.app.core.kb_loader import get_kb
for module in (engine, envelope_schema, real_data):
    assert Path(module.__file__).resolve().is_relative_to(installed), module.__file__
dishes = real_data.load_dishes()
assert len(dishes) == 214
record = get_patient('P0007')
assert record['patient_id'] == 'P0007'
proposal = run_rules_service(record)['envelope']
assert proposal.status.value == 'REJECTED'
assert proposal.scope_eligible is False
assert proposal.targets == []
kb = get_kb()
assert kb.stats()['node_counts']
assert envelope_schema.NutrientEnvelope.model_json_schema(by_alias=True, mode='serialization')['$defs']
assert not (installed / 'data').exists()
print('CARELOOP_SMOKE=' + json.dumps({'dishes': len(dishes), 'proposal': proposal.envelope_id,
                                    'module_root': str(installed), 'kb_loaded': True}))
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(installed), str(ROOT)],
                            cwd=work, env=env, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    # Native shutdown diagnostics can follow the result; they are not its payload.
    results = [line.removeprefix("CARELOOP_SMOKE=") for line in result.stdout.splitlines()
               if line.startswith("CARELOOP_SMOKE=")]
    assert len(results) == 1, result.stdout + result.stderr
    assert json.loads(results[0])["kb_loaded"] is True
    from backend.storage.postgres import PostgresConnection
    with PostgresConnection(pg_databases["clinical"], "clinical", readonly=True) as connection:
        row = connection.execute("SELECT COUNT(*) FROM envelope_journal").fetchone()
        assert row is not None and row[0] == 1
