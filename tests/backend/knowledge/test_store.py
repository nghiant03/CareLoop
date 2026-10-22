"""Exercise authoring/review/publication against isolated databases, never live state."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import psycopg.sql
import pytest

from backend.knowledge.store import KnowledgeStore, load_release
from backend.knowledge.validation import content_hash, validate_documents

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def documents():
    from backend.datasets.paths import dataset_path
    return json.loads(dataset_path("rules.json").read_text()), json.loads(dataset_path("dishes.json").read_text())


@pytest.fixture
def store(pg_databases):
    store = KnowledgeStore(pg_databases["knowledge"])
    store.initialize()
    return store


def _approved(store, documents, draft_id="initial"):
    rules, dishes = documents
    store.create_draft(draft_id, rules, dishes, actor="Author")
    store.review(draft_id, actor="Reviewer", decision="approve", expected_revision=1, note="Operator review")


def test_publication_requires_review_and_journal_is_immutable(store, documents):
    rules, dishes = documents
    summary = store.create_draft("initial", rules, dishes, actor="Author")
    assert summary["validation"]["unverified_dishes"] == 214
    assert summary["validation"]["clinical_validation"] == "not_established"
    with pytest.raises(ValueError, match="approving review"):
        store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Publish")
    with pytest.raises(ValueError, match="differ"):
        store.review("initial", actor=" author ", decision="approve", expected_revision=1, note="Review")
    with pytest.raises(ValueError, match="required"):
        store.review("initial", actor="Reviewer", decision="approve", expected_revision=1, note=" ")
    store.review("initial", actor="Reviewer", decision="approve", expected_revision=1, note="Reviewed estimates")
    release = store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Publish estimates")
    assert release.rules_document() == rules and release.dishes() == dishes
    assert release.rules_hash == content_hash(rules)
    assert [event["action"] for event in store.history("initial")] == ["create", "review", "publish"]
    assert store.show("initial")["release_id"] == "release-1"
    detached = release.dishes()
    detached.clear()
    assert len(release.dishes()) == 214
    with pytest.raises(ValueError, match="immutable"):
        store.edit_draft("initial", rules, dishes, actor="Author", expected_revision=1, note="Cannot edit")
    for table in ("knowledge_drafts", "knowledge_revisions", "knowledge_reviews", "knowledge_releases", "knowledge_events"):
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="immutable"),
            psycopg.connect(store.database) as connection,
        ):
            connection.execute(psycopg.sql.SQL("DELETE FROM {}").format(psycopg.sql.Identifier(table)))


def test_edit_invalidates_review_and_stale_updates_fail(store, documents):
    _approved(store, documents)
    rules, dishes = documents
    edited = copy.deepcopy(rules)
    edited["rules"][0]["notes"] += " Reviewed clarification."
    with pytest.raises(ValueError, match="stale"):
        store.edit_draft("initial", edited, dishes, actor="Editor", expected_revision=2, note="Edit")
    summary = store.edit_draft("initial", edited, dishes, actor="Editor", expected_revision=1, note="Clarify")
    assert summary["revision"] == 2 and summary["review"] is None
    with pytest.raises(ValueError, match="stale"):
        store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Stale")
    with pytest.raises(ValueError, match="approving review"):
        store.publish("initial", "release-1", actor="Publisher", expected_revision=2, note="Needs review")
    with pytest.raises(ValueError, match="differ"):
        store.review("initial", actor="editor", decision="approve", expected_revision=2, note="Cannot self-review")
    store.review("initial", actor="Reviewer", decision="reject", expected_revision=2, note="Not ready")
    with pytest.raises(ValueError, match="approving review"):
        store.publish("initial", "release-1", actor="Publisher", expected_revision=2, note="Rejected")
    with psycopg.connect(store.database) as connection:
        assert connection.execute("SELECT count(*) FROM knowledge_revisions").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM knowledge_releases").fetchone() == (0,)


def test_competing_edits_have_one_winner(store, documents):
    rules, dishes = documents
    store.create_draft("initial", rules, dishes, actor="Author")
    def edit(actor):
        try:
            store.edit_draft("initial", rules, dishes, actor=actor, expected_revision=1, note="Concurrent edit")
            return "saved"
        except ValueError as error:
            assert "stale" in str(error)
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(edit, ["Editor1", "Editor2"])) == ["saved", "stale"]
    assert store.show("initial")["revision"] == 2


@pytest.mark.parametrize("change", ["remove", "nutrients", "tags"])
def test_catalogue_semantics_cannot_rewrite_historical_ids(store, documents, change):
    _approved(store, documents)
    store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Initial")
    rules, dishes = copy.deepcopy(documents)
    if change == "remove":
        dishes.pop(0)
    elif change == "nutrients":
        dishes[0]["sodium_mg"] += 1
    else:
        dishes[0]["tags"].append("changed")
    _approved(store, (rules, dishes), "changed")
    with pytest.raises(ValueError, match="published dish semantics"):
        store.publish("changed", "release-2", actor="Publisher", expected_revision=1, note="Must not rewrite")
    assert load_release(store.database, "release-1").dishes() == documents[1]


def test_new_dish_ids_and_rule_changes_can_be_published(store, documents):
    _approved(store, documents)
    store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Initial")
    rules, dishes = copy.deepcopy(documents)
    corrected = {**dishes[0], "dish_id": "SG-CORRECTED-1", "sodium_mg": 1100}
    dishes.append(corrected)
    rules["rules"][0]["actions"][0]["value"] = 2200
    store.create_draft("next", rules, dishes, actor="Author", parent_release="release-1")
    store.review("next", actor="Reviewer", decision="approve", expected_revision=1, note="Review change")
    second = store.publish("next", "release-2", actor="Publisher", expected_revision=1, note="Reviewed change")
    assert len(second.dishes()) == 215
    assert second.rules_hash != load_release(store.database, "release-1").rules_hash
    assert store.show("next")["parent_release"] == "release-1"


@pytest.mark.parametrize("case", ["duplicate_rule", "unknown_condition", "bad_action", "nan", "missing_nutrient", "boolean", "duplicate_dish", "scope_removed"])
def test_validation_rejects_invalid_or_scope_unsafe_documents(documents, case):
    rules, dishes = documents
    if case == "duplicate_rule":
        rules["rules"].append(copy.deepcopy(rules["rules"][0]))
    elif case == "unknown_condition":
        rules["rules"][0]["conditions"][0]["field"] = "typo"
    elif case == "bad_action":
        rules["rules"][0]["actions"][0]["kind"] = "typo"
    elif case == "nan":
        dishes[0]["sodium_mg"] = float("nan")
    elif case == "boolean":
        dishes[0]["sodium_mg"] = True
    elif case == "missing_nutrient":
        del dishes[0]["sodium_mg"]
    elif case == "duplicate_dish":
        dishes.append(copy.deepcopy(dishes[0]))
    else:
        rules["rules"] = [rule for rule in rules["rules"] if rule["rule_id"] != "SCOPE-PREGNANCY-EXCLUDE"]
    with pytest.raises((ValueError, TypeError)):
        validate_documents(rules, dishes)


def test_runtime_reader_rejects_drafts_missing_files_and_corruption(store, documents, tmp_path):
    _approved(store, documents)
    with pytest.raises(ValueError, match="not found"):
        load_release(store.database, "initial")
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        load_release(missing, "release-1")
    assert not missing.exists()
    store.publish("initial", "release-1", actor="Publisher", expected_revision=1, note="Publish")
    with psycopg.connect(store.database) as connection:
        connection.execute("DROP TRIGGER knowledge_revisions_immutable ON knowledge_revisions")
        connection.execute("UPDATE knowledge_revisions SET rules_hash='tampered'")
        connection.commit()
    with pytest.raises(ValueError, match="checksum"):
        load_release(store.database, "release-1")


def test_initialization_refuses_the_clinical_database(pg_databases):
    database = pg_databases["clinical"]
    with pytest.raises(RuntimeError, match="Wrong"):
        KnowledgeStore(database).initialize()
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM patients").fetchone() == (0,)


def test_historical_revisions_and_release_name_collisions_preserve_content(store, documents):
    rules, dishes = documents
    store.create_draft("initial", rules, dishes, actor="Author")
    updated = copy.deepcopy(rules)
    updated["rules"][0]["notes"] += " New draft note."
    store.edit_draft("initial", updated, dishes, actor="Author", expected_revision=1, note="Edit note")
    assert store.documents("initial", 1) == (rules, dishes)
    assert store.documents("initial", 2) == (updated, dishes)
    with pytest.raises(ValueError, match="not found"):
        store.documents("initial", 3)
    store.review("initial", actor="Reviewer", decision="approve", expected_revision=2, note="Review")
    original = store.publish("initial", "release-1", actor="Publisher", expected_revision=2, note="Publish")
    _approved(store, documents, "other")
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.publish("other", "release-1", actor="Publisher", expected_revision=1, note="Collision")
    assert store.show("other")["release_id"] is None
    assert [event["action"] for event in store.history("other")] == ["create", "review"]
    before = store.history("initial")
    assert load_release(store.database, "release-1") == original
    assert store.history("initial") == before


def test_legacy_envelopes_do_not_gain_invented_knowledge_provenance():
    from shared.envelope_schema import NutrientEnvelope

    legacy = {"envelope_id": "ENV-LEGACY-001", "patient_id": "LEGACY", "targets": [],
              "patient_snapshot": {"patient_id": "LEGACY", "age": 60, "sex": "M", "weight_kg": 70},
              "priority_basis": "historical"}
    envelope = NutrientEnvelope.model_validate(legacy)
    assert envelope.knowledge_release_id is None
    assert envelope.knowledge_source_hashes == {}
