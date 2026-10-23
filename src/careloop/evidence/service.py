"""Transactional evidence operations. Call inside one database transaction.

Writes share a catalogue lock: reviews/publications cannot race with edits or retirement.
Revision bodies and source snapshots are immutable through this service.
"""

import hashlib
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from careloop.evidence.conflicts import analyse
from careloop.evidence.models import (
    BatchInput,
    Decision,
    DraftInput,
    PublicationInput,
    RetirementInput,
    RevisionInput,
    SourceInput,
)
from careloop.patients.service import invalidate_evidence
from careloop.workflow import WorkflowError, lock_catalogue, record_event, require_role


def begin_write(conn, decision: Decision):
    require_role(decision, "reviewer")
    return lock_catalogue(conn)


def audit(conn, decision, action, entity_id, details):
    record_event(conn, decision, action, entity_id, details)
    conn.execute("UPDATE evidence_catalogue SET generation = generation + 1")


def source(conn, source_id):
    row = conn.execute("SELECT * FROM evidence_sources WHERE id = %s", (source_id,)).fetchone()
    if row is None:
        raise WorkflowError(404, "Source not found")
    row["document"] = conn.execute(
        """SELECT original_sha256, metadata, refresh_of FROM evidence_documents
        WHERE source_id=%s""",
        (source_id,),
    ).fetchone()
    return row


def create_source(conn, data: SourceInput, extracted_passages=None):
    begin_write(conn, data)
    source_id = uuid4()
    checksum = hashlib.sha256(data.content.encode()).hexdigest()
    conn.execute(
        """INSERT INTO evidence_sources (id, title, locator, edition, content, content_sha256)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (source_id, data.title, data.locator, data.edition, data.content, checksum),
    )
    chunks = (
        extracted_passages
        if extracted_passages is not None
        else [
            {
                "ordinal": start // 1800 + 1,
                "location": "Submitted text",
                "content": data.content[start : start + 1800],
                "start_offset": start,
                "end_offset": min(start + 1800, len(data.content)),
            }
            for start in range(0, len(data.content), 1800)
        ]
    )
    for chunk in chunks:
        conn.execute(
            "INSERT INTO evidence_passages VALUES (%s,%s,%s,%s,%s,%s)",
            (
                source_id,
                chunk["ordinal"],
                chunk["location"],
                chunk["content"],
                chunk["start_offset"],
                chunk["end_offset"],
            ),
        )
    audit(conn, data, "source.created", source_id, {"content_sha256": checksum})
    return source(conn, source_id)


def get_rule(conn, rule_id):
    row = conn.execute("SELECT * FROM evidence_rules WHERE id = %s", (rule_id,)).fetchone()
    if row is None:
        raise WorkflowError(404, "Rule not found")
    row["revisions"] = conn.execute(
        """SELECT r.*, a.actor AS approved_by, a.approved_at
           FROM evidence_revisions r LEFT JOIN evidence_approvals a
           USING (rule_id, revision) WHERE rule_id = %s ORDER BY revision""",
        (rule_id,),
    ).fetchall()
    return row


def save_draft(conn, data: DraftInput, rule_id: UUID | None = None):
    begin_write(conn, data)
    snapshot = source(conn, data.body.source_id)
    if data.body.quote not in snapshot["content"]:
        raise WorkflowError(422, "Supporting quote must occur verbatim in the source snapshot")
    revision = 1
    if rule_id is not None:
        previous = get_rule(conn, rule_id)
        if previous["retired"]:
            raise WorkflowError(409, "Retired rules cannot be edited; create a new rule")
        if (
            not isinstance(data, RevisionInput)
            or data.expected_revision != previous["latest_revision"]
        ):
            raise WorkflowError(409, "Rule changed; reload before editing")
        revision = previous["latest_revision"] + 1
        conn.execute(
            "UPDATE evidence_rules SET latest_revision = %s WHERE id = %s", (revision, rule_id)
        )
    else:
        rule_id = uuid4()
        conn.execute("INSERT INTO evidence_rules (id, latest_revision) VALUES (%s, 1)", (rule_id,))
    body = data.body.model_dump(mode="json")
    conn.execute(
        """INSERT INTO evidence_revisions (rule_id, revision, source_id, body)
           VALUES (%s, %s, %s, %s)""",
        (rule_id, revision, data.body.source_id, Jsonb(body)),
    )
    audit(conn, data, "rule.drafted", rule_id, {"revision": revision, "body": body})
    return get_rule(conn, rule_id)


def validate_selection(conn, data: BatchInput, *, publishing=False):
    for ref in data.rules:
        rule = get_rule(conn, ref.rule_id)
        if rule["retired"] or rule["latest_revision"] != ref.revision:
            raise WorkflowError(409, "Selection contains a retired or outdated revision")
        latest = rule["revisions"][-1]
        if latest["body"]["blockers"]:
            raise WorkflowError(
                409, "Resolve all selected rule blockers before approval/publication"
            )
        if publishing:
            if latest["approved_by"] is None:
                raise WorkflowError(409, "Every selected revision must be approved")
            if rule["active_revision"] == ref.revision:
                raise WorkflowError(409, "Selected revision is already published")


def approve(conn, data: BatchInput):
    begin_write(conn, data)
    validate_selection(conn, data)
    for ref in data.rules:
        inserted = conn.execute(
            """INSERT INTO evidence_approvals (rule_id, revision, actor, reason)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING rule_id""",
            (ref.rule_id, ref.revision, data.actor.name, data.reason),
        ).fetchone()
        if inserted:
            audit(conn, data, "rule.approved", ref.rule_id, {"revision": ref.revision})
    return {"approved": [ref.model_dump(mode="json") for ref in data.rules]}


def conflict_report(conn, data):
    generation = begin_write(conn, data)
    validate_selection(conn, data)
    rows = conn.execute("""SELECT r.id AS rule_id, v.revision, v.body
        FROM evidence_rules r JOIN evidence_revisions v
        ON (v.rule_id,v.revision)=(r.id,r.active_revision) WHERE NOT r.retired""").fetchall()
    combined = {str(row["rule_id"]): row for row in rows}
    for ref in data.rules:
        combined[str(ref.rule_id)] = conn.execute(
            """SELECT rule_id, revision, body FROM evidence_revisions
               WHERE rule_id=%s AND revision=%s""",
            (ref.rule_id, ref.revision),
        ).fetchone()
    result = analyse(
        [combined[key] for key in sorted(combined)], {str(ref.rule_id) for ref in data.rules}
    )
    return {"generation": generation, **result}


def publish(conn, data: PublicationInput):
    generation = begin_write(conn, data)
    if generation != data.expected_generation:
        raise WorkflowError(409, "Evidence catalogue changed; repeat conflict review")
    validate_selection(conn, data, publishing=True)
    conflicts = conflict_report(conn, data)
    if conflicts["blocking_conflicts"]:
        raise WorkflowError(
            409, "Resolve incompatible numeric rules before publication; see conflict-check"
        )
    publication_id = uuid4()
    conn.execute(
        """INSERT INTO evidence_publications (id, actor, reason, conflict_review)
           VALUES (%s, %s, %s, %s)""",
        (publication_id, data.actor.name, data.reason, data.conflict_review),
    )
    for ref in data.rules:
        conn.execute(
            "INSERT INTO evidence_publication_rules VALUES (%s, %s, %s)",
            (publication_id, ref.rule_id, ref.revision),
        )
        conn.execute(
            "UPDATE evidence_rules SET active_revision = %s WHERE id = %s",
            (ref.revision, ref.rule_id),
        )
    audit(
        conn,
        data,
        "evidence.published",
        publication_id,
        {
            "rules": [ref.model_dump(mode="json") for ref in data.rules],
            "reviewed_generation": generation,
            "conflict_review": data.conflict_review,
            "structured_conflict_check": conflicts,
        },
    )
    invalidate_evidence(conn, data)
    return {"publication_id": publication_id}


def retire(conn, rule_id, data: RetirementInput):
    begin_write(conn, data)
    rule = get_rule(conn, rule_id)
    if rule["retired"] or rule["latest_revision"] != data.expected_revision:
        raise WorkflowError(409, "Rule changed or is already retired")
    conn.execute("UPDATE evidence_rules SET retired = true WHERE id = %s", (rule_id,))
    audit(conn, data, "rule.retired", rule_id, {"active_revision": rule["active_revision"]})
    invalidate_evidence(conn, data)
    return get_rule(conn, rule_id)


def catalogue(conn):
    # One statement gives the caller a consistent generation + rule snapshot.
    return conn.execute("""
        SELECT generation, COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id', r.id, 'latest_revision', r.latest_revision,
                'active_revision', r.active_revision, 'retired', r.retired,
                'draft', v.body, 'approved_by', a.actor, 'published', p.body
            ) ORDER BY r.id)
            FROM evidence_rules r
            JOIN evidence_revisions v ON (v.rule_id, v.revision) = (r.id, r.latest_revision)
            LEFT JOIN evidence_approvals a ON (a.rule_id, a.revision) = (r.id, r.latest_revision)
            LEFT JOIN evidence_revisions p ON (p.rule_id, p.revision) = (r.id, r.active_revision)
        ), '[]'::jsonb) AS rules FROM evidence_catalogue
    """).fetchone()
