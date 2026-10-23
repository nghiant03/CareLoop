from datetime import date
from decimal import Decimal
from uuid import uuid4

from psycopg.types.json import Jsonb

from careloop.foods.models import Nutrients
from careloop.foods.service import get_food
from careloop.logging.models import LogInput
from careloop.patients.engine import UNITS
from careloop.patients.service import get_patient, get_target
from careloop.planning.service import get_plan
from careloop.workflow import WorkflowError, lock_catalogue, record_event


def begin(conn, patient_id, data):
    if data.actor.role not in {"patient", "clinician"}:
        raise WorkflowError(403, "Logging requires the patient or clinician demo role")
    lock_catalogue(conn)
    get_patient(conn, patient_id)


def get_log(conn, patient_id, log_id):
    row = conn.execute(
        """SELECT l.*, r.body FROM meal_logs l JOIN meal_log_revisions r
        ON (r.log_id, r.revision) = (l.id, l.latest_revision)
        WHERE l.id = %s AND l.patient_id = %s""",
        (log_id, patient_id),
    ).fetchone()
    if row is None:
        raise WorkflowError(404, "Meal log not found")
    return row


def snapshot(conn, patient_id, data):
    meal = None
    if data.plan_id:
        plan = get_plan(conn, data.plan_id)
        if plan["patient_id"] != patient_id:
            raise WorkflowError(422, "Plan belongs to another patient")
        if not plan["approved_at"]:
            raise WorkflowError(409, "Only previously approved plans can be logged")
        day = (data.logged_on - date.fromisoformat(plan["request"]["start_date"])).days + 1
        meal = next(
            (
                m
                for m in plan["body"]["meals"]
                if m["day"] == day and m["slot"] == data.slot and m.get("item", 1) == data.item
            ),
            None,
        )
        if meal is None:
            raise WorkflowError(422, "No planned meal on this date and slot")
    body = data.model_dump(mode="json", exclude={"actor", "reason", "expected_revision"})
    body["planned_meal"] = meal
    if data.status == "skipped":
        body["consumed"] = None
        body["nutrients"] = dict.fromkeys(Nutrients.model_fields, "0")
        return body
    if data.status in {"replaced", "independent"}:
        food = get_food(conn, data.food_id)
        consumed = {
            "food_id": str(data.food_id),
            "food_revision": food["latest_revision"],
            "food": food["body"],
            "portion_id": data.portion_id,
            "scale": data.scale,
        }
    else:
        consumed = dict(meal)
        if data.status == "changed_quantity":
            consumed["scale"] = data.scale
    food = consumed["food"]
    unit = food.get("basis", "g")
    portion = next((p for p in food["portions"] if p["id"] == consumed["portion_id"]), None)
    field = "grams" if unit == "g" else "millilitres"
    if portion is None or portion.get(field) is None:
        raise WorkflowError(422, "Portion missing or incompatible with food units")
    quantity = Decimal(str(portion[field])) * Decimal(str(consumed["scale"]))
    consumed.update(quantity=str(quantity), unit=unit)
    body["consumed"] = consumed
    body["nutrients"] = {
        key: None
        if food["nutrients"].get(key) is None
        else str(Decimal(str(food["nutrients"][key])) * quantity / 100)
        for key in Nutrients.model_fields
    }
    return body


def save_log(conn, patient_id, data, log_id=None):
    begin(conn, patient_id, data)
    revision = 1
    if log_id:
        previous = get_log(conn, patient_id, log_id)
        if previous["latest_revision"] != data.expected_revision:
            raise WorkflowError(409, "Meal log changed; reload before correcting")
        if (previous["logged_on"], previous["plan_id"], previous["slot"], previous["item"]) != (
            data.logged_on,
            data.plan_id,
            data.slot,
            data.item,
        ):
            raise WorkflowError(422, "Corrections must retain date, plan, slot and item")
        revision = previous["latest_revision"] + 1
    elif (
        data.plan_id
        and conn.execute(
            """SELECT id FROM meal_logs WHERE patient_id=%s AND plan_id=%s
        AND logged_on=%s AND slot=%s AND item=%s""",
            (patient_id, data.plan_id, data.logged_on, data.slot, data.item),
        ).fetchone()
    ):
        raise WorkflowError(409, "Planned meal already logged; correct its existing entry")
    body = snapshot(conn, patient_id, data)
    if log_id is None:
        log_id = uuid4()
        conn.execute(
            """INSERT INTO meal_logs
            (id, patient_id, logged_on, plan_id, slot, item, latest_revision)
            VALUES (%s,%s,%s,%s,%s,%s,1)""",
            (log_id, patient_id, data.logged_on, data.plan_id, data.slot, data.item),
        )
    else:
        conn.execute("UPDATE meal_logs SET latest_revision=%s WHERE id=%s", (revision, log_id))
    conn.execute(
        "INSERT INTO meal_log_revisions (log_id, revision, body) VALUES (%s,%s,%s)",
        (log_id, revision, Jsonb(body)),
    )
    conn.execute(
        """INSERT INTO meal_log_days VALUES (%s,%s,false)
        ON CONFLICT (patient_id, logged_on) DO UPDATE SET complete=false""",
        (patient_id, data.logged_on),
    )
    record_event(conn, data, "meal_log.recorded", log_id, {"revision": revision})
    return get_log(conn, patient_id, log_id)


def day_summary(conn, patient_id, logged_on, plan_id=None):
    get_patient(conn, patient_id)
    rows = conn.execute(
        """SELECT l.*, r.body FROM meal_logs l JOIN meal_log_revisions r
        ON (r.log_id,r.revision)=(l.id,l.latest_revision)
        WHERE patient_id=%s AND logged_on=%s ORDER BY l.created_at,l.id""",
        (patient_id, logged_on),
    ).fetchall()
    day = conn.execute(
        "SELECT complete FROM meal_log_days WHERE patient_id=%s AND logged_on=%s",
        (patient_id, logged_on),
    ).fetchone()
    totals = {}
    for key in Nutrients.model_fields:
        values = [row["body"]["nutrients"][key] for row in rows]
        totals[key] = (
            None
            if not values or None in values
            else str(sum((Decimal(v) for v in values), Decimal(0)))
        )
    planned_slots = None
    if plan_id:
        plan = get_plan(conn, plan_id)
        if plan["patient_id"] != patient_id or not plan["approved_at"]:
            raise WorkflowError(422, "Select a previously approved plan for this patient")
        number = (logged_on - date.fromisoformat(plan["request"]["start_date"])).days + 1
        recorded = {
            (row["slot"], row["item"]): row["body"]["status"]
            for row in rows
            if row["plan_id"] == plan_id
        }
        planned_slots = [
            {
                "slot": meal["slot"],
                "item": meal.get("item", 1),
                "status": recorded.get((meal["slot"], meal.get("item", 1)), "unlogged"),
            }
            for meal in plan["body"]["meals"]
            if meal["day"] == number
        ]
    return {
        "logged_on": logged_on,
        "complete": bool(day and day["complete"]),
        "entries": rows,
        "recorded_totals": totals,
        "planned_slots": planned_slots,
    }


def complete_day(conn, patient_id, logged_on, data):
    begin(conn, patient_id, data)
    conn.execute(
        """INSERT INTO meal_log_days VALUES (%s,%s,%s)
        ON CONFLICT (patient_id, logged_on) DO UPDATE SET complete=EXCLUDED.complete""",
        (patient_id, logged_on, data.complete),
    )
    record_event(
        conn,
        data,
        "meal_log.day_updated",
        patient_id,
        {"logged_on": str(logged_on), "complete": data.complete},
    )
    return day_summary(conn, patient_id, logged_on)


def confirm_meal(conn, patient_id, data):
    begin(conn, patient_id, data)
    plan = get_plan(conn, data.plan_id)
    number = (data.logged_on - date.fromisoformat(plan["request"]["start_date"])).days + 1
    meals = [m for m in plan["body"]["meals"] if m["day"] == number and m["slot"] == data.slot]
    if not meals:
        raise WorkflowError(422, "No planned meal on this date and slot")
    # Keep one transaction so a later item's conflict rolls back earlier inserts.
    return [
        save_log(conn, patient_id, LogInput(**data.model_dump(), item=m.get("item", 1)))
        for m in meals
    ]


def compare_targets(conn, patient_id, logged_on, target_id):
    summary = day_summary(conn, patient_id, logged_on)
    target = get_target(conn, target_id)
    if target["patient_id"] != patient_id:
        raise WorkflowError(422, "Target set belongs to another patient")
    revision = target["approved_revision"]
    if revision is None:
        raise WorkflowError(409, "Comparison requires a clinician-approved target revision")
    body = next(row["body"] for row in target["revisions"] if row["revision"] == revision)
    comparisons = []
    for item in body["items"]:
        action = item["action"]
        value = summary["recorded_totals"].get(action["subject"])
        status = "unknown_intake"
        difference = None
        if action["kind"] not in {"range", "ceiling", "intake"} or UNITS.get(
            action["subject"]
        ) != action.get("unit"):
            status = "not_numerically_comparable"
        elif value is not None:
            amount, actual = Decimal(str(action["amount"])), Decimal(value)
            difference = str(actual - amount)
            if action["kind"] == "ceiling":
                status = (
                    "above_ceiling"
                    if actual > amount
                    else ("within_ceiling" if summary["complete"] else "partial_within_ceiling")
                )
            elif action["kind"] == "range":
                if actual > Decimal(str(action["upper"])):
                    status = "above_range"
                elif not summary["complete"]:
                    status = "partial_day"
                else:
                    status = "below_range" if actual < amount else "within_range"
            else:
                status = (
                    "at_or_above_goal"
                    if actual >= amount
                    else ("below_goal" if summary["complete"] else "partial_below_goal")
                )
        comparisons.append(
            {
                "target_item": item,
                "recorded": value,
                "status": status,
                "difference_from_amount": difference,
            }
        )
    return {
        "logged_on": logged_on,
        "complete": summary["complete"],
        "target_id": target_id,
        "approved_revision": revision,
        "target_needs_review": target["needs_review"] or revision != target["latest_revision"],
        "comparisons": comparisons,
        "scope": "Reported intake, not a clinical outcome assessment",
    }
