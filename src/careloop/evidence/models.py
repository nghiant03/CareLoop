from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=10000)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Actor(Model):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Literal["reviewer", "clinician", "patient"]


class Decision(Model):
    actor: Actor
    reason: Text


class SourceInput(Decision):
    title: Text
    locator: Text
    edition: Text
    content: Annotated[str, Field(min_length=1, max_length=10_000_000)]


class Predicate(Model):
    fact: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
    operator: Literal["eq", "gte", "lte", "contains"]
    value: str | float | bool


class Action(Model):
    kind: Literal[
        "intake", "minimum", "ceiling", "range", "additional", "exclusion", "timing", "assessment"
    ]
    subject: Text
    amount: Annotated[float, Field(ge=0)] | None = None
    upper: Annotated[float, Field(ge=0)] | None = None
    unit: Text | None = None
    advice: Text
    upper_exclusive: bool = False

    @model_validator(mode="after")
    def numeric_shape(self):
        numeric = self.kind in {"intake", "minimum", "ceiling", "range", "additional"}
        if self.upper_exclusive and self.kind != "ceiling":
            raise ValueError("Only ceilings support an exclusive upper bound")
        if self.unit == "%energy":
            from careloop.nutrition import ENERGY_FACTORS

            if self.subject not in ENERGY_FACTORS or self.kind == "additional":
                raise ValueError("Unsupported energy-percentage action")
            if any(v is not None and v > 100 for v in (self.amount, self.upper)):
                raise ValueError("Energy percentages must be between 0 and 100")
        if numeric and (self.amount is None or self.unit is None):
            raise ValueError("Numeric recommendations require an amount and unit")
        if not numeric and any(v is not None for v in (self.amount, self.upper, self.unit)):
            raise ValueError("Qualitative guidance cannot contain numerical limits")
        if self.kind == "range":
            if self.upper is None or self.upper < self.amount:
                raise ValueError("A range requires an upper bound >= its lower amount")
        elif self.upper is not None:
            raise ValueError("Only range recommendations have an upper bound")
        return self


class RuleBody(Model):
    review_role: Literal["required", "advisory"] = "required"
    review_note: Text | None = None
    source_id: UUID
    quote: Text
    location: Text
    applicability: Annotated[list[Predicate], Field(max_length=50)]
    population_note: Text
    exceptions: Annotated[list[Predicate], Field(max_length=50)]
    exception_note: Text
    action: Action
    blockers: Annotated[list[Text], Field(max_length=50)] = Field(default_factory=list)

    @model_validator(mode="after")
    def advisory_scope(self):
        if self.review_role == "advisory" and (
            self.action.kind != "assessment" or not self.review_note
        ):
            raise ValueError("Advisory guidance requires an assessment action and review note")
        return self


class DraftInput(Decision):
    body: RuleBody


class RevisionInput(DraftInput):
    expected_revision: Annotated[int, Field(gt=0)]


class RuleRef(Model):
    rule_id: UUID
    revision: Annotated[int, Field(gt=0)]


class BatchInput(Decision):
    rules: Annotated[list[RuleRef], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_rules(self):
        if len({ref.rule_id for ref in self.rules}) != len(self.rules):
            raise ValueError("Select each rule only once")
        return self


class PublicationInput(BatchInput):
    expected_generation: Annotated[int, Field(ge=0)]
    conflict_review: Text


class RetirementInput(Decision):
    expected_revision: Annotated[int, Field(gt=0)]
