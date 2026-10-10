"""Patient models.

``PatientSummary`` is the canonical audit-friendly subset frozen inside every
envelope (re-exported from ``shared/``). ``Patient`` is the richer synthetic
profile accepted by the patient API. The richer dataset-generator model is
``data.patient.Patient``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.envelope_schema import PatientSummary

__all__ = ["PatientSummary", "Patient"]


class Patient(BaseModel):
    """Extended patient record accepted by the patient API.

    Extra keys are allowed so the synthetic generator can evolve its schema without
    breaking the API. ``to_summary()`` projects down to the frozen envelope
    contract.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    patient_id: str
    name: str = ""
    age: int = Field(..., ge=0, le=130)
    sex: Literal["F", "M", "X"]
    weight_kg: float = Field(..., gt=0)
    height_cm: Optional[float] = Field(default=None, gt=0)
    diagnoses: list[str] = Field(default_factory=list)
    egfr: Optional[float] = Field(default=None, ge=0)
    serum_k_meq_l: Optional[float] = Field(default=None, ge=0, alias="serum_K_meq_L")
    serum_po4_mg_dl: Optional[float] = Field(default=None, ge=0, alias="serum_PO4_mg_dL")
    meds: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None

    def to_summary(self) -> PatientSummary:
        """Project this record onto the canonical envelope patient snapshot."""
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
