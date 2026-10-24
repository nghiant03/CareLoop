from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from careloop.evidence.models import Decision, Text
from careloop.foods.models import Slot


class FoodPool(Decision):
    # Omitted/null means catalogue; an explicitly empty custom pool is invalid.
    food_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)] | None = None
    excluded_food_ids: Annotated[list[UUID], Field(max_length=100)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_food_pool(self):
        for ids in (self.food_ids or [], self.excluded_food_ids):
            if len(set(ids)) != len(ids):
                raise ValueError("Food IDs must not contain duplicates")
        if set(self.food_ids or []) & set(self.excluded_food_ids):
            raise ValueError("A food cannot be both selected and excluded")
        return self


class PlanInput(FoodPool):
    target_id: UUID
    target_revision: Annotated[int, Field(gt=0)]
    start_date: date
    days: Annotated[int, Field(ge=1, le=7)]
    schedule: Annotated[list[Slot], Field(min_length=1, max_length=4)] = Field(
        default_factory=lambda: ["breakfast", "lunch", "dinner"]
    )
    items_per_slot: dict[Slot, Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_selection(self):
        if not set(self.items_per_slot) <= set(self.schedule):
            raise ValueError("Item counts must refer to scheduled meal slots")
        if len(set(self.schedule)) != len(self.schedule):
            raise ValueError("Schedule must not contain duplicates")
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


class RecommendationInput(FoodPool):
    day: Annotated[int, Field(ge=1, le=7)]
    slot: Slot
    item: Annotated[int, Field(ge=1, le=5)] = 1
    method: Literal["cluster", "nearest", "same_category"] = "nearest"
    clusters: Annotated[int, Field(ge=1, le=8)] = 4
    limit: Annotated[int, Field(ge=1, le=20)] = 5
