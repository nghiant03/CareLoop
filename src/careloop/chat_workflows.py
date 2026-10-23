"""Deterministic workflow attachments and revision stamps for cited conversation."""

import hashlib
import json
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from careloop.evidence.models import Model
from careloop.foods.models import Slot
from careloop.logging import service as logging
from careloop.patients.engine import UNITS
from careloop.planning import service as planning
from careloop.planning.models import RecommendationInput
from careloop.planning.recommendations import recommend
from careloop.workflow import WorkflowError

NUTRIENT_UNITS = {key: unit.removesuffix("/day") for key, unit in UNITS.items()}


class SubstitutionSelection(Model):
    day: Annotated[int, Field(ge=1, le=7)]
    slot: Slot
    item: Annotated[int, Field(ge=1, le=5)] = 1
    food_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_foods(self):
        if len(set(self.food_ids)) != len(self.food_ids):
            raise ValueError("Food IDs must be unique")
        return self


class Selection(Model):
    plan_id: UUID | None = None
    logged_on: date | None = None
    substitution: SubstitutionSelection | None = None

    @model_validator(mode="after")
    def needs_plan(self):
        if self.substitution and not self.plan_id:
            raise ValueError("Select an approved plan for substitution suggestions")
        return self


def encoded(value):
    return json.dumps(value, sort_keys=True, default=str)


def selected_plan(conn, patient_id, selection, target_id, target_revision):
    plan = planning.get_plan(conn, selection.plan_id)
    if str(plan["patient_id"]) != str(patient_id):
        raise WorkflowError(422, "Select a plan belonging to this patient")
    if (
        not plan["approved_at"]
        or plan["needs_review"]
        or str(plan["target_id"]) != str(target_id)
        or plan["target_revision"] != target_revision
    ):
        raise WorkflowError(409, "Chat requires a current approved plan for the selected targets")
    return plan


def stamp(conn, patient_id, selection, target_id, target_revision):
    """Track only selected records; unrelated patient activity does not stale an answer."""
    state = {}
    if selection.plan_id:
        plan = selected_plan(conn, patient_id, selection, target_id, target_revision)
        state["plan"] = {
            k: plan[k] for k in ("id", "approved_at", "needs_review", "selected_plan_id", "body")
        }
    if selection.logged_on:
        state["logs"] = conn.execute(
            """SELECT id, latest_revision FROM meal_logs
            WHERE patient_id=%s AND logged_on=%s ORDER BY id""",
            (patient_id, selection.logged_on),
        ).fetchall()
        state["day"] = conn.execute(
            "SELECT complete FROM meal_log_days WHERE patient_id=%s AND logged_on=%s",
            (patient_id, selection.logged_on),
        ).fetchone()
    if selection.substitution:
        state["foods"] = conn.execute(
            "SELECT id, latest_revision FROM foods WHERE id=ANY(%s) ORDER BY id",
            (selection.substitution.food_ids,),
        ).fetchall()
    return hashlib.sha256(encoded(state).encode()).hexdigest()


def source(identity, kind, title, location, value, **metadata):
    return {
        "id": identity,
        "kind": kind,
        "title": title,
        "location": location,
        "text": encoded(value),
        **metadata,
    }


def attach(conn, patient_id, selection, snapshot, decision):
    references, suggestions = [], None
    if selection.plan_id:
        plan = selected_plan(
            conn, patient_id, selection, snapshot["target_id"], snapshot["target_revision"]
        )
        for day, totals in plan["body"]["check"]["daily_totals"].items():
            meals = [
                {
                    "slot": m["slot"],
                    "item": m.get("item", 1),
                    "name": m["food"]["name"],
                    "food_id": m["food_id"],
                    "food_revision": m["food_revision"],
                    "quantity": m["quantity"],
                    "unit": m["unit"],
                    "portion_id": m["portion_id"],
                }
                for m in plan["body"]["meals"]
                if m["day"] == int(day)
            ]
            references.append(
                source(
                    f"plan:{plan['id']}:day:{day}",
                    "approved_plan",
                    "Approved meal plan",
                    f"Day {day} · starts {plan['request']['start_date']}",
                    {
                        "meals": meals,
                        "daily_totals": totals,
                        "check_valid": plan["body"]["check"]["valid"],
                        "objective": plan["objective"],
                        "start_date": plan["request"]["start_date"],
                        "nutrient_units": NUTRIENT_UNITS,
                        "day": int(day),
                        "target_id": snapshot["target_id"],
                    },
                    plan_id=str(plan["id"]),
                )
            )
    if selection.logged_on:
        summary = logging.day_summary(conn, patient_id, selection.logged_on, selection.plan_id)
        comparison = logging.compare_targets(
            conn, patient_id, selection.logged_on, UUID(snapshot["target_id"])
        )
        references.append(
            source(
                f"intake:{selection.logged_on}",
                "recorded_intake",
                "Reported intake and completeness",
                str(selection.logged_on),
                {k: v for k, v in summary.items() if k != "entries"}
                | {"nutrient_units": NUTRIENT_UNITS},
            )
        )
        for row in summary["entries"]:
            body = row["body"]
            consumed = body.get("consumed") or {}
            planned = body.get("planned_meal") or {}
            references.append(
                source(
                    f"log:{row['id']}:{row['latest_revision']}",
                    "recorded_intake",
                    "Recorded meal item",
                    f"{selection.logged_on} · {row['slot']} · item {row['item']}",
                    {
                        "status": body["status"],
                        "nutrients": body["nutrients"],
                        "name": consumed.get("food", {}).get("name"),
                        "quantity": consumed.get("quantity"),
                        "unit": consumed.get("unit"),
                        "food_revision": consumed.get("food_revision"),
                        "food_id": consumed.get("food_id"),
                        "planned_name": planned.get("food", {}).get("name"),
                        "plan_id": row["plan_id"],
                        "nutrient_units": NUTRIENT_UNITS,
                    },
                )
            )
        for index, item in enumerate(comparison["comparisons"]):
            references.append(
                source(
                    f"comparison:{selection.logged_on}:{index}",
                    "intake_comparison",
                    "Calculated target comparison",
                    str(selection.logged_on),
                    {**item, "complete": comparison["complete"], "scope": comparison["scope"]},
                )
            )
    if selection.substitution:
        data = RecommendationInput(**decision, **selection.substitution.model_dump())
        result = recommend(conn, selection.plan_id, data)
        suggestions = {"plan_id": str(selection.plan_id), **result}
        references.append(
            source(
                "substitution-search",
                "checked_substitution",
                "Checked substitution search",
                f"Day {data.day} · {data.slot} · item {data.item}",
                {
                    k: result[k]
                    for k in (
                        "method",
                        "pool_revisions",
                        "eligible_foods",
                        "checked_portions",
                        "approval_required",
                        "infeasibility_proven",
                    )
                },
            )
        )
        for index, candidate in enumerate(result["recommendations"]):
            references.append(
                source(
                    f"substitution:{index}",
                    "checked_substitution",
                    candidate["name"],
                    f"Day {data.day} · {data.slot} · item {data.item}",
                    {k: v for k, v in candidate.items() if k != "check"}
                    | {
                        "check_valid": candidate["check"]["valid"],
                        "approval_required": True,
                        "daily_totals": candidate["check"]["daily_totals"][str(data.day)],
                        "nutrient_units": NUTRIENT_UNITS,
                    },
                )
            )
    return references, suggestions
