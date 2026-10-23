from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from careloop.evidence.models import Decision, Text
from careloop.foods.models import Slot


class PlanInput(Decision):
    target_id: UUID
    target_revision: Annotated[int, Field(gt=0)]
    start_date: date
    days: Annotated[int, Field(ge=1, le=7)]
    schedule: Annotated[list[Slot], Field(min_length=1, max_length=4)] = Field(
        default_factory=lambda: ["breakfast", "lunch", "dinner"]
    )
    food_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    items_per_slot: dict[Slot, Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_selection(self):
        if not set(self.items_per_slot) <= set(self.schedule):
            raise ValueError("Item counts must refer to scheduled meal slots")
        if len(set(self.schedule)) != len(self.schedule) or len(set(self.food_ids)) != len(
            self.food_ids
        ):
            raise ValueError("Schedule and food IDs must not contain duplicates")
        return self


class PlanApproval(Decision):
    review_note: Text


class SubstitutionInput(Decision):
    day: Annotated[int, Field(ge=1, le=7)]
    slot: Slot
    item: Annotated[int, Field(ge=1, le=5)] = 1
    food_id: UUID
    portion_id: Text
    scale: Literal[0.5, 1.0, 1.5] = 1.0


class RecommendationInput(Decision):
    day: Annotated[int, Field(ge=1, le=7)]
    slot: Slot
    item: Annotated[int, Field(ge=1, le=5)] = 1
    food_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    method: Literal["cluster", "nearest", "same_category"] = "nearest"
    clusters: Annotated[int, Field(ge=1, le=8)] = 4
    limit: Annotated[int, Field(ge=1, le=20)] = 5

    @model_validator(mode="after")
    def unique_foods(self):
        if len(set(self.food_ids)) != len(self.food_ids):
            raise ValueError("Food IDs must be unique")
        return self
