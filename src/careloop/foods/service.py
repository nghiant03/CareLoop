from uuid import uuid4

from psycopg.types.json import Jsonb

from careloop.planning.invalidation import flag_plans
from careloop.workflow import WorkflowError, lock_catalogue, record_event, require_role


def get_food(conn, food_id):
    row = conn.execute(
        """SELECT f.*, r.body,
        (SELECT jsonb_agg(jsonb_build_object('revision', h.revision, 'body', h.body,
          'created_at', h.created_at) ORDER BY h.revision)
          FROM food_revisions h WHERE h.food_id = f.id) AS revisions
        FROM foods f JOIN food_revisions r ON (r.food_id, r.revision) = (f.id, f.latest_revision)
        WHERE f.id = %s""",
        (food_id,),
    ).fetchone()
    if row is None:
        raise WorkflowError(404, "Food not found")
    return row


def planning_pool(conn, food_ids=None, excluded_food_ids=()):
    if food_ids is not None:
        return [get_food(conn, identity) for identity in sorted(food_ids)]
    rows = conn.execute(
        """SELECT f.id, f.latest_revision, r.body FROM foods f JOIN food_revisions r
        ON (r.food_id, r.revision) = (f.id, f.latest_revision) ORDER BY f.id"""
    ).fetchall()
    excluded = {str(identity) for identity in excluded_food_ids}
    if excluded - {str(row["id"]) for row in rows}:
        raise WorkflowError(404, "An excluded food no longer exists")
    return [row for row in rows if str(row["id"]) not in excluded]


def save_food(conn, data, food_id=None):
    require_role(data, "reviewer")
    lock_catalogue(conn)
    revision = 1
    if food_id is None:
        if conn.execute(
            "SELECT id FROM foods WHERE namespace = %s AND external_id = %s",
            (data.namespace, data.external_id),
        ).fetchone():
            raise WorkflowError(409, "Food source identity already exists")
        food_id = uuid4()
        conn.execute(
            "INSERT INTO foods VALUES (%s, 1, %s, %s)", (food_id, data.namespace, data.external_id)
        )
    else:
        previous = get_food(conn, food_id)
        if previous["latest_revision"] != data.expected_revision:
            raise WorkflowError(409, "Food changed; reload before editing")
        revision = previous["latest_revision"] + 1
        conn.execute("UPDATE foods SET latest_revision = %s WHERE id = %s", (revision, food_id))
        flag_plans(conn, data, "food_changed", food_id=food_id)
    body = data.body.model_dump(mode="json")
    conn.execute(
        "INSERT INTO food_revisions (food_id, revision, body) VALUES (%s, %s, %s)",
        (food_id, revision, Jsonb(body)),
    )
    record_event(conn, data, "food.recorded", food_id, {"revision": revision, "body": body})
    return get_food(conn, food_id)
