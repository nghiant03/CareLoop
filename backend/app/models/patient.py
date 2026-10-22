from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.envelope_schema import PatientSummary

__all__ = ["Patient", "PatientSummary"]


class Patient(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    patient_id: str
    name: str = ""
    age: int = Field(..., ge=0, le=130)
    sex: Literal["F", "M", "X"]
    weight_kg: float = Field(..., gt=0)
    height_cm: float | None = Field(default=None, gt=0)
    diagnoses: list[str] = Field(default_factory=list)
    egfr: float | None = Field(default=None, ge=0)
    serum_k_meq_l: float | None = Field(default=None, ge=0, alias="serum_K_meq_L")
    serum_po4_mg_dl: float | None = Field(default=None, ge=0, alias="serum_PO4_mg_dL")
    meds: list[str] = Field(default_factory=list)
    created_at: str | None = None

    @field_validator("weight_kg", "height_cm", "egfr", "serum_k_meq_l", "serum_po4_mg_dl")
    @classmethod
    def _require_finite(cls, value: float | None) -> float | None:
        """Numeric bounds alone admit positive infinity."""
        if value is not None and not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    def to_summary(self) -> PatientSummary:
        return PatientSummary(
            patient_id=self.patient_id,
            age=self.age,
            sex=self.sex,
            weight_kg=self.weight_kg,
            diagnoses=list(self.diagnoses),
            egfr=self.egfr,
            serum_K_meq_L=self.serum_k_meq_l,
            serum_PO4_mg_dL=self.serum_po4_mg_dl,
            meds=list(self.meds),
        )
