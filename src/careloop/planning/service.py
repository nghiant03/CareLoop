from uuid import uuid4

from psycopg.types.json import Jsonb

from careloop.foods.service import get_food
from careloop.patients.service import get_target, require_current
from careloop.planning.checker import check_plan, portion_quantity
from careloop.planning.invalidation import flag_plans
from careloop.planning.search import generate
from careloop.workflow import WorkflowError, lock_catalogue, record_event, require_role


def begin(conn, data):
    if data.actor.role not in {"patient", "clinician"}:
        raise WorkflowError(403, "Planning requires the patient or clinician demo role")
    lock_catalogue(conn)


def current_context(conn, target_id, revision):
    target = get_target(conn, target_id)
    patient = require_current(conn, target, revision)
    if target["approved_revision"] != revision:
        raise WorkflowError(409, "Planning requires clinician-approved current targets")
    return target, patient["body"]["facts"]


def get_plan(conn, plan_id):
    row = conn.execute(
        """SELECT p.*, r.patient_id, r.target_id, r.target_revision,
        r.body AS request, r.selected_plan_id FROM plans p
        JOIN plan_requests r ON r.id = p.request_id
        WHERE p.id = %s""",
        (plan_id,),
    ).fetchone()
    if row is None:
        raise WorkflowError(404, "Plan not found")
    return row


def store_plan(conn, data, request_id, alternative, parent_plan_id=None):
    plan_id = uuid4()
    conn.execute(
        """INSERT INTO plans (id, request_id, parent_plan_id, objective, body)
        VALUES (%s, %s, %s, %s, %s)""",
        (plan_id, request_id, parent_plan_id, alternative["objective"], Jsonb(alternative)),
    )
    for meal in alternative["meals"]:
        conn.execute(
            "INSERT INTO plan_foods VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (plan_id, meal["food_id"], meal["food_revision"]),
        )
    record_event(
        conn,
        data,
        "plan.drafted",
        plan_id,
        {"request_id": str(request_id), "valid": alternative["check"]["valid"]},
    )
    return get_plan(conn, plan_id)


def request_plans(conn, data):
    begin(conn, data)
    target, facts = current_context(conn, data.target_id, data.target_revision)
    foods = [get_food(conn, food_id) for food_id in sorted(data.food_ids)]
    alternatives, outcome = generate(foods, data, facts, target["body"]["items"])
    request_id = uuid4()
    request_body = data.model_dump(mode="json", exclude={"actor", "reason"})
    conn.execute(
        """INSERT INTO plan_requests
        (id, patient_id, target_id, target_revision, body, outcome)
        VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            request_id,
            target["patient_id"],
            data.target_id,
            data.target_revision,
            Jsonb(request_body),
            Jsonb(outcome),
        ),
    )
    plans = [store_plan(conn, data, request_id, alternative) for alternative in alternatives]
    record_event(conn, data, "planning.requested", request_id, outcome)
    return {"request_id": request_id, "outcome": outcome, "alternatives": plans}


def approve_plan(conn, plan_id, data):
    require_role(data, "clinician")
    lock_catalogue(conn)
    plan = get_plan(conn, plan_id)
    target, facts = current_context(conn, plan["target_id"], plan["target_revision"])
    if plan["needs_review"] or plan["approved_at"] or plan["selected_plan_id"]:
        raise WorkflowError(409, "Plan is stale or an alternative has already been selected")
    if plan["parent_plan_id"]:
        parent = get_plan(conn, plan["parent_plan_id"])
        if parent["needs_review"] or not parent["approved_at"]:
            raise WorkflowError(409, "Substitution parent changed; request a new draft")
    for meal in plan["body"]["meals"]:
        food = get_food(conn, meal["food_id"])
        if food["latest_revision"] != meal["food_revision"]:
            raise WorkflowError(409, "Food catalogue changed; request new alternatives")
    check = check_plan(
        plan["body"]["meals"],
        plan["request"]["days"],
        plan["request"]["schedule"],
        facts,
        target["body"]["items"],
    )
    if not check["valid"]:
        raise WorkflowError(409, "An unmet draft cannot be approved")
    conn.execute(
        "UPDATE plans SET approved_by = %s, approved_at = now() WHERE id = %s",
        (data.actor.name, plan_id),
    )
    conn.execute(
        "UPDATE plan_requests SET selected_plan_id = %s WHERE id = %s",
        (plan_id, plan["request_id"]),
    )
    if plan["parent_plan_id"]:
        flag_plans(conn, data, "substitution_approved", plan_id=plan["parent_plan_id"])
    record_event(
        conn, data, "plan.approved", plan_id, {"review_note": data.review_note, "check": check}
    )
    return get_plan(conn, plan_id)


def substitute(conn, plan_id, data):
    begin(conn, data)
    plan = get_plan(conn, plan_id)
    target, facts = current_context(conn, plan["target_id"], plan["target_revision"])
    if plan["needs_review"] or not plan["approved_at"]:
        raise WorkflowError(409, "Substitutions require a current approved plan")
    index = next(
        (
            i
            for i, m in enumerate(plan["body"]["meals"])
            if m["day"] == data.day and m["slot"] == data.slot
        ),
        None,
    )
    if index is None:
        raise WorkflowError(422, "Requested meal does not exist")
    food = get_food(conn, data.food_id)
    try:
        quantity = portion_quantity(food["body"], data.portion_id, data.scale)
    except ValueError as exc:
        raise WorkflowError(422, str(exc)) from exc
    meals = list(plan["body"]["meals"])
    meals[index] = {
        "day": data.day,
        "slot": data.slot,
        "food_id": str(data.food_id),
        "food_revision": food["latest_revision"],
        "food": food["body"],
        "portion_id": data.portion_id,
        "scale": data.scale,
        "quantity": str(quantity),
        "unit": food["body"].get("basis", "g"),
    }
    check = check_plan(
        meals, plan["request"]["days"], plan["request"]["schedule"], facts, target["body"]["items"]
    )
    request_id = uuid4()
    conn.execute(
        """INSERT INTO plan_requests
        (id, patient_id, target_id, target_revision, body, outcome)
        VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            request_id,
            plan["patient_id"],
            plan["target_id"],
            plan["target_revision"],
            Jsonb(plan["request"]),
            Jsonb({"status": "draft" if check["valid"] else "unmet_draft"}),
        ),
    )
    return store_plan(
        conn,
        data,
        request_id,
        {"objective": "substitution", "meals": meals, "check": check},
        plan_id,
    )
