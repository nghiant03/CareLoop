"""CareLoop data models.

Re-exports the canonical contracts from ``shared/envelope_schema.py`` plus the
patient API profile model. The dataset generator uses ``backend.datasets.patient.Patient``.
"""

from __future__ import annotations

from backend.app.models.envelope import (
    CitationSource,
    ConstraintKind,
    EnvelopeStatus,
    ExclusionFlag,
    ExclusionKind,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
    RuleFire,
)
from backend.app.models.patient import Patient

__all__ = [
    "CitationSource",
    "ConstraintKind",
    "EnvelopeStatus",
    "ExclusionFlag",
    "ExclusionKind",
    "NutrientConstraint",
    "NutrientEnvelope",
    "NutrientKind",
    "Patient",
    "PatientSummary",
    "RuleFire",
]
