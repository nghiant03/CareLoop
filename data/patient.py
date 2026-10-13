"""Extend canonical patient snapshots with synthetic vitals and lab histories.

Serialize with ``by_alias=True`` to retain the wire lab names
``serum_K_meq_L`` and ``serum_PO4_mg_dL``.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from shared.envelope_schema import PatientSummary


class Patient(PatientSummary):
    """A full synthetic patient record.

    Adds archetype, vitals and longitudinal labs to the frozen rule-input model.
    Monthly lab arrays store the current value at index 0, then older values.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    archetype: str = Field(
        ...,
        description="Clinical archetype label, e.g. 'CKD4_T2D_HTN'",
    )
    exclude_from_careloop: bool = Field(
        default=False,
        description="True for out-of-scope cases (e.g. pregnancy) that must not be planned for.",
    )

    height_cm: float = Field(..., gt=0, le=250)
    # Full generated records require BMI; historical summaries may omit it.
    bmi: float = Field(..., gt=0, le=100)  # pyrefly: ignore[bad-override-mutable-attribute]
    hba1c_pct: float | None = Field(default=None, ge=0, le=20)
    systolic_bp: int | None = Field(default=None, ge=0, le=300)
    diastolic_bp: int | None = Field(default=None, ge=0, le=200)

    labs_K_monthly: list[float] = Field(
        default_factory=list,
        description="6 most-recent monthly serum K (meq/L), index 0 = most recent.",
    )
    labs_PO4_monthly: list[float] = Field(
        default_factory=list,
        description="6 most-recent monthly serum phosphate (mg/dL), index 0 = most recent.",
    )
    months_offset_ago: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5],
        description="Months before today for each longitudinal entry (0 = current).",
    )

    notes: str | None = Field(default=None)

    def to_summary(self) -> PatientSummary:
        """Project to the canonical audit snapshot used inside envelopes."""
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
            snapshot_version=2,
            bmi=self.bmi,
            pregnant=self.pregnant if self.pregnant is not None else "pregnancy" in self.diagnoses,
            hba1c_pct=self.hba1c_pct,
        )


__all__ = ["Patient"]
