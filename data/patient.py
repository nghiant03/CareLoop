"""Synthetic patient records with clinical archetypes and longitudinal labs.

Defines the *full* patient record used by the synthetic generator. It extends the
canonical :class:`shared.envelope_schema.PatientSummary` (the audit-friendly subset
frozen with every envelope) with the extra fields the mining / trend-detection
modules need: clinical archetype, longitudinal monthly labs, vitals and body
composition.

Import contract
---------------
``PatientSummary`` is reused verbatim so that a ``Patient`` can always be
projected down to the canonical snapshot via :meth:`Patient.to_summary`.

Serialisation note
------------------
``PatientSummary`` declares ``serum_k_meq_l`` / ``serum_po4_mg_dl`` with the
aliases ``serum_K_meq_L`` / ``serum_PO4_mg_dL`` (``populate_by_name=True``).
The generator writes JSON with ``by_alias=True`` so the on-disk shape uses the
canonical aliases.
"""

from __future__ import annotations

from typing import Optional

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
    bmi: float = Field(..., gt=0, le=100)
    hba1c_pct: Optional[float] = Field(default=None, ge=0, le=20)
    systolic_bp: Optional[int] = Field(default=None, ge=0, le=300)
    diastolic_bp: Optional[int] = Field(default=None, ge=0, le=200)

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

    notes: Optional[str] = Field(default=None)

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
