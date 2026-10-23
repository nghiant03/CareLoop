from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator

from careloop.evidence.models import Action, Decision, Model, RuleRef, Text


# Null = unknown. Empty lists and false are explicit, known observations.
class Facts(Model):
    observed_on: date | None = None
    age_years: Annotated[StrictFloat, Field(ge=2, le=120)] | None = None
    sex: Literal["female", "male", "other"] | None = None
    pregnant: StrictBool | None = None
    breastfeeding: StrictBool | None = None
    weight_kg: Annotated[StrictFloat, Field(gt=0, le=700)] | None = None
    height_cm: Annotated[StrictFloat, Field(gt=0, le=300)] | None = None
    egfr: Annotated[StrictFloat, Field(ge=0, le=250)] | None = None
    has_ckd: StrictBool | None = None
    ckd_stage: Literal["G1", "G2", "G3a", "G3b", "G4", "G5"] | None = None
    dialysis: StrictBool | None = None
    conditions: list[Text] | None = None
    medications: list[Text] | None = None
    allergies: list[Text] | None = None
    vegetarian: StrictBool | None = None
    include_eggs: StrictBool | None = None
    include_dairy: StrictBool | None = None
    dislikes: list[Text] | None = None

    @model_validator(mode="after")
    def consistent_ckd_status(self):
        if self.ckd_stage is not None:
            if self.has_ckd is False:
                raise ValueError("CKD stage cannot be recorded when CKD status is No")
            # Preserve legacy records that already explicitly record a CKD stage.
            self.has_ckd = True
        return self


class Provenance(Model):
    kind: Literal["manual", "csv", "public_dataset"]
    source: Text
    edition: Text | None = None
    record_id: Text | None = None
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    notes: Text


class PatientBody(Model):
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    facts: Facts
    provenance: Provenance


class PatientInput(Decision):
    body: PatientBody
    external_namespace: Text | None = None
    external_id: Text | None = None

    @model_validator(mode="after")
    def external_pair(self):
        if (self.external_namespace is None) != (self.external_id is None):
            raise ValueError("external_namespace and external_id must be supplied together")
        return self


class PatientEdit(Decision):
    body: PatientBody
    expected_revision: Annotated[int, Field(gt=0)]


class CSVInput(Decision):
    content: Annotated[StrictStr, Field(min_length=1, max_length=5_000_000)]


class ProposalInput(Decision):
    expected_patient_revision: Annotated[int, Field(gt=0)]


class ManualTarget(Model):
    action: Action
    rationale: Text


class Disposition(Model):
    rule: RuleRef
    reason: Text


class TargetEdit(Decision):
    expected_revision: Annotated[int, Field(gt=0)]
    selected: Annotated[list[RuleRef], Field(max_length=100)]
    manual: Annotated[list[ManualTarget], Field(max_length=100)]
    dispositions: Annotated[list[Disposition], Field(max_length=100)]


class TargetApproval(Decision):
    expected_revision: Annotated[int, Field(gt=0)]
    completeness_note: Text
