from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from careloop.evidence.models import Decision, Text
from careloop.foods.models import Slot


class LogInput(Decision):
    logged_on: date
    slot: Slot
    item: Annotated[int, Field(ge=1, le=5)] = 1
    plan_id: UUID | None = None
    status: Literal["as_planned", "changed_quantity", "replaced", "skipped", "independent"]
    food_id: UUID | None = None
    portion_id: Text | None = None
    scale: Annotated[float, Field(gt=0, le=100)] | None = None
    note: Annotated[str, Field(max_length=10000)] = ""

    @model_validator(mode="after")
    def shape(self):
        if (self.status == "independent") != (self.plan_id is None):
            raise ValueError("Independent entries omit plan_id; other statuses require it")
        if self.status in {"independent", "replaced"}:
            if self.food_id is None or self.portion_id is None or self.scale is None:
                raise ValueError("Food, portion and scale are required")
        elif self.food_id is not None or self.portion_id is not None:
            raise ValueError("This status uses the pinned planned food and portion")
        if self.status == "changed_quantity" and self.scale is None:
            raise ValueError("Changed quantity requires an absolute portion scale")
        if self.status in {"as_planned", "skipped"} and self.scale is not None:
            raise ValueError("This status does not accept a scale")
        return self


class LogEdit(LogInput):
    expected_revision: Annotated[int, Field(gt=0)]


class DayInput(Decision):
    complete: bool


class MealConfirmation(Decision):
    plan_id: UUID
    logged_on: date
    slot: Slot
    status: Literal["as_planned", "skipped"] = "as_planned"
