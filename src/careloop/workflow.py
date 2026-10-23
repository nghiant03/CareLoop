from psycopg.types.json import Jsonb


class WorkflowError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


def require_role(decision, role):
    if decision.actor.role != role:
        raise WorkflowError(403, f"This operation requires the {role} demo role")


def lock_catalogue(conn):
    return conn.execute(
        "SELECT generation FROM evidence_catalogue WHERE singleton FOR UPDATE"
    ).fetchone()["generation"]


def record_event(conn, decision, action, entity_id, details):
    conn.execute(
        """INSERT INTO audit_events (actor, action, entity_id, reason, details)
           VALUES (%s, %s, %s, %s, %s)""",
        (decision.actor.name, action, entity_id, decision.reason, Jsonb(details)),
    )
