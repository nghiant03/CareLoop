from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from careloop.evidence.models import Decision, Model, Text
from careloop.patients.models import Provenance

Slot = Literal["breakfast", "lunch", "dinner", "snack"]
Allergen = Literal[
    "egg",
    "milk",
    "peanut",
    "tree_nut",
    "soy",
    "wheat",
    "fish",
    "shellfish",
    "sesame",
    "gluten",
    "sulphite",
    "celery",
    "mustard",
    "lupin",
    "mollusc",
]
Amount = Annotated[float, Field(ge=0, le=1_000_000)]


class Nutrients(Model):
    # Per 100 units of the food's basis (g or ml); kcal, mg minerals, otherwise g.
    energy: Amount | None = None
    protein: Amount | None = None
    carbohydrate: Amount | None = None
    fat: Amount | None = None
    saturated_fat: Amount | None = None
    fibre: Amount | None = None
    total_sugars: Amount | None = None
    added_sugars: Amount | None = None
    free_sugars: Amount | None = None
    sodium: Amount | None = None
    potassium: Amount | None = None
    phosphorus: Amount | None = None


class Portion(Model):
    id: Annotated[str, Field(min_length=1, max_length=100)]
    label: Text
    grams: Annotated[float, Field(gt=0, le=10000)] | None = None
    millilitres: Annotated[float, Field(gt=0, le=10000)] | None = None

    @model_validator(mode="after")
    def one_unit(self):
        if (self.grams is None) == (self.millilitres is None):
            raise ValueError("Supply exactly one of grams or millilitres; no assumed density")
        return self


class FoodBody(Model):
    name: Text
    category: Text
    basis: Literal["g", "ml"] = "g"
    nutrients: Nutrients
    portions: Annotated[list[Portion], Field(max_length=100)]
    provenance: Provenance
    source_details: dict[str, str] = Field(default_factory=dict)
    import_warnings: list[Text] = Field(default_factory=list)
    ingredients: list[Text] | None = None
    allergen_status: dict[Allergen, Literal["present", "absent", "unknown"]] = Field(
        default_factory=dict
    )
    vegetarian: StrictBool | None = None
    contains_egg: StrictBool | None = None
    contains_dairy: StrictBool | None = None
    meal_slots: list[Slot] = Field(default_factory=list)
    planning_portions: list[str] = Field(default_factory=list)
    review_note: Text | None = None

    @model_validator(mode="after")
    def reviewed_fields(self):
        for portion in self.portions:
            if (self.basis == "g") != (portion.grams is not None):
                raise ValueError("Portion units must match the nutrient basis")
        ids = [portion.id for portion in self.portions]
        if len(set(ids)) != len(ids):
            raise ValueError("Portion IDs must be unique")
        if not set(self.planning_portions) <= set(ids):
            raise ValueError("Planning portions must reference supplied portions")
        if len(set(self.meal_slots)) != len(self.meal_slots):
            raise ValueError("Meal slots must be unique")
        annotations = (
            self.allergen_status
            or self.meal_slots
            or self.planning_portions
            or self.vegetarian is not None
            or self.contains_egg is not None
            or self.contains_dairy is not None
            or self.ingredients is not None
        )
        if annotations and not self.review_note:
            raise ValueError("Reviewer annotations require a supporting review note")
        return self


class FoodInput(Decision):
    namespace: Text
    external_id: Text
    body: FoodBody


class FoodEdit(Decision):
    expected_revision: Annotated[int, Field(gt=0)]
    body: FoodBody
