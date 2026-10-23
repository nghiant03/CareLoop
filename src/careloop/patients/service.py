"""Patient/target writes share the evidence lock to make reassessment atomic."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from careloop.patients import engine
from careloop.planning.invalidation import flag_plans
from careloop.workflow import WorkflowError, lock_catalogue, record_event, require_role


def begin(conn, decision):
    require_role(decision, "clinician")
    lock_catalogue(conn)


def get_patient(conn, patient_id):
    row = conn.execute(
        """
        SELECT p.*, r.body, r.created_at,
            (SELECT jsonb_agg(jsonb_build_object('revision', h.revision, 'body', h.body,
             'created_at', h.created_at) ORDER BY h.revision)
             FROM patient_revisions h WHERE h.patient_id = p.id) AS revisions
        FROM patients p JOIN patient_revisions r
          ON (r.patient_id, r.revision) = (p.id, p.latest_revision) WHERE p.id = %s
    """,
        (patient_id,),
    ).fetchone()
    if row is None:
        raise WorkflowError(404, "Patient not found")
    return row


def save_patient(conn, data, patient_id=None):
    begin(conn, data)
    revision = 1
    if patient_id is None:
        patient_id = uuid4()
        if (
            data.external_id is not None
            and conn.execute(
                "SELECT id FROM patients WHERE external_namespace = %s AND external_id = %s",
                (data.external_namespace, data.external_id),
            ).fetchone()
        ):
            raise WorkflowError(409, "External patient record already imported")
        conn.execute(
            """INSERT INTO patients
            (id, latest_revision, external_namespace, external_id) VALUES (%s, 1, %s, %s)""",
            (patient_id, data.external_namespace, data.external_id),
        )
    else:
        previous = get_patient(conn, patient_id)
        if previous["latest_revision"] != data.expected_revision:
            raise WorkflowError(409, "Patient changed; reload before editing")
        revision = previous["latest_revision"] + 1
        conn.execute(
            "UPDATE patients SET latest_revision = %s WHERE id = %s", (revision, patient_id)
        )
        invalidate(
            conn,
            data,
            "patient_changed",
            patient_id=patient_id,
            facts=data.body.facts.model_dump(mode="json"),
        )
    body = data.body.model_dump(mode="json")
    conn.execute(
        "INSERT INTO patient_revisions (patient_id, revision, body) VALUES (%s, %s, %s)",
        (patient_id, revision, Jsonb(body)),
    )
    record_event(conn, data, "patient.recorded", patient_id, {"revision": revision, "body": body})
    return get_patient(conn, patient_id)


def active_rules(conn):
    return conn.execute("""
        SELECT v.rule_id, v.revision, v.body FROM evidence_rules r
        JOIN evidence_revisions v ON (v.rule_id, v.revision) = (r.id, r.active_revision)
        WHERE NOT r.retired ORDER BY r.id
    """).fetchall()


def get_target(conn, target_id):
    row = conn.execute(
        """
        SELECT t.*, v.body,
            (SELECT jsonb_agg(jsonb_build_object('revision', h.revision, 'body', h.body,
             'created_at', h.created_at) ORDER BY h.revision)
             FROM target_revisions h WHERE h.target_id = t.id) AS revisions
        FROM target_sets t JOIN target_revisions v
          ON (v.target_id, v.revision) = (t.id, t.latest_revision) WHERE t.id = %s
    """,
        (target_id,),
    ).fetchone()
    if row is None:
        raise WorkflowError(404, "Target set not found")
    return row


def invalidate(conn, decision, reason, *, patient_id=None, facts=None):
    changed = conn.execute(
        """
        UPDATE target_sets SET needs_review = true,
            review_reasons = review_reasons || %s::jsonb
        WHERE NOT needs_review AND (%s::uuid IS NULL OR patient_id = %s) RETURNING id
    """,
        (Jsonb([reason]), patient_id, patient_id),
    ).fetchall()
    for row in changed:
        record_event(conn, decision, "targets.flagged", row["id"], {"reason": reason})
    # `changed` omits already-flagged targets; their plans still need new allergy alerts.
    targets = conn.execute(
        "SELECT id FROM target_sets WHERE patient_id = %s", (patient_id,)
    ).fetchall()
    for row in targets:
        flag_plans(conn, decision, reason, target_id=row["id"], facts=facts)


def invalidate_evidence(conn, decision):
    """Caller holds the evidence lock until target and plan flags are saved."""
    rules = active_rules(conn)
    # A newly applicable rule will not appear in a target's stored rule references.
    candidates = conn.execute("""
        SELECT t.id, t.evaluation, p.body FROM target_sets t JOIN patient_revisions p
        ON (p.patient_id, p.revision) = (t.patient_id, t.patient_revision)
        WHERE NOT t.needs_review
    """).fetchall()
    for candidate in candidates:
        current = engine.evaluate(rules, candidate["body"]["facts"])
        if engine.signature(current) != engine.signature(candidate["evaluation"]):
            conn.execute(
                """UPDATE target_sets SET needs_review = true,
                review_reasons = review_reasons || '["evidence_changed"]'::jsonb WHERE id = %s""",
                (candidate["id"],),
            )
            record_event(
                conn, decision, "targets.flagged", candidate["id"], {"reason": "evidence_changed"}
            )
            flag_plans(conn, decision, "evidence_changed", target_id=candidate["id"])


def blockers(evaluation, items, dispositions, facts):
    result = engine.target_blockers(evaluation, items, dispositions)
    if facts.get("age_years") is None:
        result.append({"missing": ["age_years"], "issue": "Age is required for target approval"})
    if facts.get("dialysis") is True:
        result.append({"issue": "Dialysis is outside the supported population"})
    return result


def propose(conn, patient_id, data):
    begin(conn, data)
    patient = get_patient(conn, patient_id)
    if patient["latest_revision"] != data.expected_patient_revision:
        raise WorkflowError(409, "Patient changed; reload before proposing targets")
    facts = patient["body"]["facts"]
    evaluation = engine.evaluate(active_rules(conn), facts)
    items = [engine.evidence_item(r) for r in evaluation if r["status"] == "applicable"]
    body = {"items": items, "dispositions": [], "blockers": blockers(evaluation, items, [], facts)}
    target_id = uuid4()
    conn.execute(
        """INSERT INTO target_sets
        (id, patient_id, patient_revision, evaluation, latest_revision)
        VALUES (%s, %s, %s, %s, 1)""",
        (target_id, patient_id, patient["latest_revision"], Jsonb(evaluation)),
    )
    conn.execute(
        "INSERT INTO target_revisions (target_id, revision, body) VALUES (%s, 1, %s)",
        (target_id, Jsonb(body)),
    )
    record_event(
        conn,
        data,
        "targets.proposed",
        target_id,
        {"patient_id": str(patient_id), "patient_revision": patient["latest_revision"]},
    )
    return get_target(conn, target_id)


def require_current(conn, target, expected_revision):
    if target["needs_review"] or target["latest_revision"] != expected_revision:
        raise WorkflowError(409, "Target set is stale; create a new proposal or reload")
    patient = get_patient(conn, target["patient_id"])
    if patient["latest_revision"] != target["patient_revision"]:
        raise WorkflowError(409, "Patient facts changed; create a new proposal")
    current = engine.evaluate(active_rules(conn), patient["body"]["facts"])
    if engine.signature(current) != engine.signature(target["evaluation"]):
        raise WorkflowError(409, "Published evidence changed; create a new proposal")
    return patient


def edit_target(conn, target_id, data):
    begin(conn, data)
    target = get_target(conn, target_id)
    patient = require_current(conn, target, data.expected_revision)
    if target["approved_revision"] is not None:
        raise WorkflowError(409, "Approved targets are immutable; create a new proposal")
    results = {(r["rule_id"], r["revision"]): r for r in target["evaluation"]}
    items, seen = [], set()
    for ref in data.selected:
        key = (str(ref.rule_id), ref.revision)
        result = results.get(key)
        if key in seen or result is None or result["status"] != "applicable":
            raise WorkflowError(422, "Select each applicable rule revision only once")
        seen.add(key)
        items.append(engine.evidence_item(result))
    dispositions = []
    for disposition in data.dispositions:
        ref = disposition.rule
        key = (str(ref.rule_id), ref.revision)
        if (
            key in seen
            or key not in results
            or results[key]["status"] not in {"applicable", "needs_clinician"}
        ):
            raise WorkflowError(422, "Disposition must reference an unselected, actionable rule")
        seen.add(key)
        dispositions.append(disposition.model_dump(mode="json"))
    for manual in data.manual:
        action = manual.action
        if action.kind in {"assessment", "additional"} or (
            action.kind in {"intake", "ceiling", "range"}
            and engine.UNITS.get(action.subject) != action.unit
        ):
            raise WorkflowError(422, "Manual targets require a completed action in supported units")
        items.append(
            {
                "origin": "clinician",
                "author": data.actor.name,
                "rationale": manual.rationale,
                "action": action.model_dump(mode="json"),
            }
        )
    body = {
        "items": items,
        "dispositions": dispositions,
        "blockers": blockers(target["evaluation"], items, dispositions, patient["body"]["facts"]),
    }
    revision = target["latest_revision"] + 1
    conn.execute("UPDATE target_sets SET latest_revision = %s WHERE id = %s", (revision, target_id))
    conn.execute(
        "INSERT INTO target_revisions (target_id, revision, body) VALUES (%s, %s, %s)",
        (target_id, revision, Jsonb(body)),
    )
    record_event(conn, data, "targets.edited", target_id, {"revision": revision, "body": body})
    return get_target(conn, target_id)


def approve_target(conn, target_id, data):
    begin(conn, data)
    target = get_target(conn, target_id)
    patient = require_current(conn, target, data.expected_revision)
    if target["approved_revision"] is not None:
        raise WorkflowError(409, "Target set already approved")
    if blockers(
        target["evaluation"],
        target["body"]["items"],
        target["body"]["dispositions"],
        patient["body"]["facts"],
    ):
        raise WorkflowError(409, "Resolve missing facts, competing targets, and review items first")
    old = conn.execute(
        """UPDATE target_sets SET needs_review = true,
        review_reasons = review_reasons || '["targets_superseded"]'::jsonb
        WHERE patient_id = %s AND id <> %s AND approved_revision IS NOT NULL AND NOT needs_review
        RETURNING id""",
        (target["patient_id"], target_id),
    ).fetchall()
    for row in old:
        record_event(conn, data, "targets.flagged", row["id"], {"reason": "targets_superseded"})
        flag_plans(conn, data, "targets_superseded", target_id=row["id"])
    conn.execute(
        """UPDATE target_sets SET approved_revision = latest_revision,
        approved_by = %s, approved_at = now() WHERE id = %s""",
        (data.actor.name, target_id),
    )
    record_event(
        conn,
        data,
        "targets.approved",
        target_id,
        {"revision": target["latest_revision"], "completeness_note": data.completeness_note},
    )
    return get_target(conn, target_id)


def target_readiness(conn, patient_id):
    get_patient(conn, patient_id)
    current = conn.execute(
        """SELECT id, approved_revision FROM target_sets
        WHERE patient_id = %s AND approved_revision IS NOT NULL AND NOT needs_review
        ORDER BY approved_at DESC, id LIMIT 1""",
        (patient_id,),
    ).fetchone()
    return {
        "targets_ready": current is not None,
        "approved_target": current,
        "reason": None if current else "Clinician approval of current targets is required",
    }
