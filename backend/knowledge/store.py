from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.knowledge.validation import (
    NUTRIENTS,
    canonical_json,
    content_hash,
    validate_documents,
)
from backend.storage.postgres import PostgresConnection, is_postgres

_DISH_SEMANTIC_FIELDS = (*NUTRIENTS, "portion_g", "category", "ingredients", "tags")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _identity(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise ValueError("draft/release ID must use 1-100 letters, digits, '.', '_' or '-'")


@dataclass(frozen=True)
class KnowledgeRelease:
    release_id: str
    rules_json: str
    dishes_json: str
    rules_hash: str
    dishes_hash: str
    published_at: str

    def rules_document(self) -> dict:
        return json.loads(self.rules_json)

    def dishes(self) -> list[dict]:
        return json.loads(self.dishes_json)

    def source_hashes(self) -> dict[str, str]:
        return {"rules/rules.json": self.rules_hash, "data/dishes.json": self.dishes_hash}


def load_release(database: str | Path, release_id: str) -> KnowledgeRelease:
    _identity(release_id)
    with KnowledgeStore(database)._connection() as conn:
        row = conn.execute("""
            SELECT p.release_id, p.published_at, r.*, v.decision
            FROM knowledge_releases p JOIN knowledge_revisions r USING(draft_id,revision)
            JOIN knowledge_reviews v USING(draft_id,revision) WHERE p.release_id=?
        """, (release_id,)).fetchone()
        if row is None or row["decision"] != "approve":
            raise ValueError(f"Published approved knowledge release not found: {release_id}")
        rules, dishes = json.loads(row["rules_json"]), json.loads(row["dishes_json"])
        if content_hash(rules) != row["rules_hash"] or content_hash(dishes) != row["dishes_hash"]:
            raise ValueError("knowledge release checksum mismatch")
        return KnowledgeRelease(release_id, row["rules_json"], row["dishes_json"],
                                row["rules_hash"], row["dishes_hash"], row["published_at"])


class KnowledgeStore:
    def __init__(self, database: str | Path):
        if not is_postgres(database):
            raise ValueError("Knowledge storage requires a PostgreSQL URL; SQLite is no longer supported")
        self.database = str(database)

    def initialize(self) -> None:
        """Verify schema without creating it."""
        with PostgresConnection(self.database, "knowledge", readonly=True):
            pass

    @contextmanager
    def _connection(self, *, write: bool = False):
        with PostgresConnection(self.database, "knowledge", readonly=not write) as conn:
            if write:
                conn.reserve_write()
            yield conn

    def _latest(self, conn, draft_id: str, expected_revision: int | None = None):
        row = conn.execute("SELECT * FROM knowledge_revisions WHERE draft_id=? ORDER BY revision DESC LIMIT 1",
                           (draft_id,)).fetchone()
        if row is None:
            raise ValueError(f"draft not found: {draft_id}")
        if expected_revision is not None and row["revision"] != expected_revision:
            raise ValueError(f"stale draft revision: expected {expected_revision}, current {row['revision']}")
        return row

    def _unpublished(self, conn, draft_id: str) -> None:
        if conn.execute("SELECT 1 FROM knowledge_releases WHERE draft_id=?", (draft_id,)).fetchone():
            raise ValueError("published drafts are immutable; clone the release into a new draft")

    def _revision(self, conn, draft_id, revision, actor, rules, dishes, validation):
        conn.execute("INSERT INTO knowledge_revisions VALUES (?,?,?,?,?,?,?,?,?)",
                     (draft_id, revision, actor, _now(), canonical_json(rules), canonical_json(dishes),
                      content_hash(rules), content_hash(dishes), canonical_json(validation)))

    def _event(self, conn, draft_id, revision, actor, action, detail):
        conn.execute("INSERT INTO knowledge_events(draft_id,revision,actor,action,detail_json,created_at) VALUES (?,?,?,?,?,?)",
                     (draft_id, revision, actor, action, canonical_json(detail), _now()))

    def create_draft(self, draft_id: str, rules: dict, dishes: list[dict], *, actor: str,
                     provenance: dict | None = None, parent_release: str | None = None) -> dict:
        _identity(draft_id)
        actor = _required(actor, "actor")
        validation = validate_documents(rules, dishes)
        with self._connection(write=True) as conn:
            if parent_release is not None and not conn.execute(
                "SELECT 1 FROM knowledge_releases WHERE release_id=?", (parent_release,)
            ).fetchone():
                raise ValueError("parent release not found")
            conn.execute("INSERT INTO knowledge_drafts VALUES (?,?,?,?,?)",
                         (draft_id, actor, _now(), parent_release, canonical_json(provenance or {})))
            self._revision(conn, draft_id, 1, actor, rules, dishes, validation)
            self._event(conn, draft_id, 1, actor, "create", {"parent_release": parent_release, "validation": validation})
        return self.show(draft_id)

    def edit_draft(self, draft_id: str, rules: dict, dishes: list[dict], *, actor: str,
                   expected_revision: int, note: str) -> dict:
        actor = _required(actor, "actor")
        note = _required(note, "note")
        validation = validate_documents(rules, dishes)
        with self._connection(write=True) as conn:
            current = self._latest(conn, draft_id, expected_revision)
            self._unpublished(conn, draft_id)
            revision = current["revision"] + 1
            self._revision(conn, draft_id, revision, actor, rules, dishes, validation)
            self._event(conn, draft_id, revision, actor, "edit", {"note": note, "validation": validation})
        return self.show(draft_id)

    def review(self, draft_id: str, *, actor: str, decision: str, expected_revision: int, note: str) -> dict:
        actor = _required(actor, "actor")
        note = _required(note, "note")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        with self._connection(write=True) as conn:
            row = self._latest(conn, draft_id, expected_revision)
            self._unpublished(conn, draft_id)
            editors = {r[0] for r in conn.execute("SELECT editor FROM knowledge_revisions WHERE draft_id=?", (draft_id,))}
            if actor.casefold() in {editor.casefold() for editor in editors}:
                raise ValueError("reviewer must differ from all authors/editors of this draft")
            validation = validate_documents(json.loads(row["rules_json"]), json.loads(row["dishes_json"]))
            conn.execute("INSERT INTO knowledge_reviews VALUES (?,?,?,?,?,?)",
                         (draft_id, expected_revision, actor, decision, note, _now()))
            self._event(conn, draft_id, expected_revision, actor, "review", {"decision": decision, "note": note,
                                                                         "validation": validation})
        return self.show(draft_id)

    def publish(self, draft_id: str, release_id: str, *, actor: str, expected_revision: int, note: str) -> KnowledgeRelease:
        _identity(release_id)
        actor = _required(actor, "actor")
        note = _required(note, "note")
        with self._connection(write=True) as conn:
            row = self._latest(conn, draft_id, expected_revision)
            self._unpublished(conn, draft_id)
            review = conn.execute("SELECT * FROM knowledge_reviews WHERE draft_id=? AND revision=?",
                                  (draft_id, expected_revision)).fetchone()
            if review is None or review["decision"] != "approve":
                raise ValueError("latest revision requires an approving review before publication")
            validate_documents(json.loads(row["rules_json"]), json.loads(row["dishes_json"]))
            catalogue = {dish["dish_id"]: dish for dish in json.loads(row["dishes_json"])}
            previous = conn.execute("SELECT r.dishes_json FROM knowledge_releases p "
                                    "JOIN knowledge_revisions r USING(draft_id,revision)").fetchall()
            for published in previous:
                for dish in json.loads(published[0]):
                    current = catalogue.get(dish["dish_id"])
                    if current is None or any(current.get(field) != dish.get(field) for field in _DISH_SEMANTIC_FIELDS):
                        raise ValueError(f"published dish semantics must be retained: {dish['dish_id']}; use a new dish ID")
            conn.execute("INSERT INTO knowledge_releases VALUES (?,?,?,?,?,?)",
                         (release_id, draft_id, expected_revision, actor, note, _now()))
            self._event(conn, draft_id, expected_revision, actor, "publish", {"release_id": release_id, "note": note})
        return load_release(self.database, release_id)

    def show(self, draft_id: str) -> dict:
        with self._connection() as conn:
            row = self._latest(conn, draft_id)
            draft = conn.execute("SELECT * FROM knowledge_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if draft is None:
                raise ValueError(f"draft not found: {draft_id}")
            result = dict(draft)
            result.update({"revision": row["revision"], "rules_hash": row["rules_hash"], "dishes_hash": row["dishes_hash"],
                           "validation": json.loads(row["validation_json"])})
            review = conn.execute("SELECT * FROM knowledge_reviews WHERE draft_id=? AND revision=?",
                                  (draft_id, row["revision"])).fetchone()
            release = conn.execute("SELECT release_id FROM knowledge_releases WHERE draft_id=?", (draft_id,)).fetchone()
            result["review"] = dict(review) if review else None
            result["release_id"] = release[0] if release else None
            result["provenance"] = json.loads(result.pop("provenance_json"))
            return result

    def documents(self, draft_id: str, revision: int | None = None) -> tuple[dict, list[dict]]:
        with self._connection() as conn:
            if revision is None:
                row = self._latest(conn, draft_id)
            else:
                row = conn.execute("SELECT * FROM knowledge_revisions WHERE draft_id=? AND revision=?",
                                   (draft_id, revision)).fetchone()
                if row is None:
                    raise ValueError("draft revision not found")
            return json.loads(row["rules_json"]), json.loads(row["dishes_json"])

    def history(self, draft_id: str) -> list[dict]:
        with self._connection() as conn:
            self._latest(conn, draft_id)
            return [dict(row) for row in conn.execute("SELECT * FROM knowledge_events WHERE draft_id=? ORDER BY event_id", (draft_id,))]

    def list_drafts(self) -> list[dict]:
        with self._connection() as conn:
            ids = [row[0] for row in conn.execute("SELECT draft_id FROM knowledge_drafts ORDER BY created_at,draft_id")]
        return [self.show(draft_id) for draft_id in ids]
