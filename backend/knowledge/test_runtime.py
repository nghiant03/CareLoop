"""Release-mode integration in fresh processes so global caches cannot leak between tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.knowledge.store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[2]
from backend.datasets.paths import dataset_path


@pytest.fixture
def published(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.initialize()
    rules = json.loads(dataset_path("rules.json").read_text())
    dishes = json.loads(dataset_path("dishes.json").read_text())
    rules["rules"][0]["actions"][0]["value"] = 2222
    dishes[0]["name"] = "DATABASE CATALOGUE MARKER"
    store.create_draft("draft-1", rules, dishes, actor="Author")
    store.review("draft-1", actor="Reviewer", decision="approve", expected_revision=1, note="Test review")
    release = store.publish("draft-1", "release-1", actor="Publisher", expected_revision=1, note="Test release")
    return store.database, release


def _run(script, database, release_id, tmp_path, *, mode="database"):
    env = {**os.environ, "CARELOOP_APP_DB": str(tmp_path / "isolated-app.sqlite3"),
           "CARELOOP_KNOWLEDGE_MODE": mode, "CARELOOP_KNOWLEDGE_DB": str(database),
           "CARELOOP_KNOWLEDGE_RELEASE": release_id}
    return subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120, check=False)


def test_all_live_consumers_use_the_database_release_and_persist_provenance(published, tmp_path):
    database, release = published
    script = '''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from backend.knowledge.runtime import selected_release
from backend.app.core.kb_loader import get_kb
from backend.app.core import persistence
from backend.app.api import dishes
from backend.app import main
from backend.optim import real_data
from backend.mining import substitutions
from rules import engine

missing = Path('/not/a/source/file.json')
engine._RULES_PATH = missing
real_data.DEFAULT_DISHES_PATH = str(missing)
substitutions.DATA_PATH = missing
dishes.DISHES_FILE = missing
import backend.app.core.kb_loader as loader
loader.RULES_PATH = loader.DISHES_PATH = missing
assert engine._ruleset()[0]['actions'][0]['value'] == 2222
assert real_data.load_dishes()[0].name == 'DATABASE CATALOGUE MARKER'
assert substitutions.load_dishes()[0]['name'] == 'DATABASE CATALOGUE MARKER'
assert dishes._load_dishes()[0]['name'] == 'DATABASE CATALOGUE MARKER'
assert any(dish['name'] == 'DATABASE CATALOGUE MARKER' for dish in get_kb().dishes())
snapshot = selected_release()
with TestClient(main.app) as client:
    response = client.post('/rules/run', json={'patient_id': 'P0001'})
    assert response.status_code == 200, response.text
    proposal = response.json()['envelope']
    assert proposal['knowledge_release_id'] == 'release-1'
    assert proposal['knowledge_source_hashes'] == snapshot.source_hashes()
    approved = client.post('/envelopes/' + proposal['envelope_id'] + '/approve', json={
        'approved_by':'Dr.KnowledgeTest', 'expected_revision':proposal['lifecycle_revision']})
    assert approved.status_code == 200, approved.text
    plan = client.post('/plans', json={'patient_id':'P0001'})
    assert plan.status_code == 200, plan.text
    document = plan.json()
    assert document['knowledge_release_id'] == 'release-1'
    assert document['source_hashes'] == snapshot.source_hashes()
    assert persistence.get_plan(document['plan_id'])['knowledge_release_id'] == 'release-1'
    assert persistence.list_plans('P0001')[0]['kb_version'] == 'release-1'
    chat = client.post('/chat', json={'patient_id':'P0001','message':'How much sodium should I eat?'})
    assert chat.status_code == 200, chat.text
    assert client.get('/dishes/SG0001').json()['name'] == 'DATABASE CATALOGUE MARKER'
os.environ['CARELOOP_KNOWLEDGE_RELEASE'] = 'different-release'
try:
    real_data.load_dishes()
except RuntimeError as error:
    assert 'restart' in str(error)
else:
    raise AssertionError('mixed process-wide knowledge configuration accepted')
print('KNOWLEDGE_OK')
'''
    result = _run(script, database, release.release_id, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KNOWLEDGE_OK" in result.stdout


@pytest.mark.parametrize("selection", ["missing-release", "draft-1", "missing-db", "missing-setting", "invalid-mode"])
def test_configured_knowledge_fails_startup_without_fallback(published, tmp_path, selection):
    database, _ = published
    release_id, mode = "release-1", "database"
    if selection in {"missing-release", "draft-1"}:
        release_id = selection
    elif selection == "missing-db":
        database = tmp_path / "absent.sqlite3"
    elif selection == "missing-setting":
        release_id = ""
    else:
        mode = "typo"
    result = _run("from fastapi.testclient import TestClient; from backend.app.main import app; "
                  "\nwith TestClient(app):\n    raise AssertionError('must not serve')", database, release_id, tmp_path, mode=mode)
    assert result.returncode != 0
    assert "must not serve" not in result.stderr
    assert not (tmp_path / "absent.sqlite3").exists()


def test_engine_and_kb_metadata_identify_the_pinned_release(published, tmp_path):
    database, release = published
    script = '''
from rules.engine import run_rules
from backend.app.api.kb import kb_stats
from backend.knowledge.runtime import selected_release
patient = {'patient_id':'RELEASE-TEST','age':60,'sex':'M','weight_kg':70,'diagnoses':['T2D']}
first = run_rules(patient)
assert run_rules(patient) == first
envelope = first['envelope']
assert envelope['knowledge_release_id'] == 'release-1'
assert envelope['knowledge_source_hashes'] == selected_release().source_hashes()
assert any(target['nutrient']=='sodium_mg' and target['value']==2222 for target in envelope['targets'])
stats = kb_stats()
assert stats['knowledge_release_id'] == 'release-1'
assert stats['knowledge_source_hashes'] == selected_release().source_hashes()
assert first['trace'] and all(row['citation']['guideline'] for row in first['trace'])
'''
    result = _run(script, database, release.release_id, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_knowledge_does_not_create_clinical_storage(published, tmp_path):
    database, _ = published
    result = _run("from fastapi.testclient import TestClient; from backend.app.main import app; "
                  "\nwith TestClient(app):\n    pass", database, "draft-1", tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / "isolated-app.sqlite3").exists()
