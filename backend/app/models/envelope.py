"""Envelope model re-export.

The single source of truth is ``shared/envelope_schema.py`` (authored jointly
with Lane A). We re-export it here so backend code has a stable import path
(``backend.app.models.envelope``) while the contract stays canonical.

Do NOT redefine the models here — edits belong in ``shared/``.
"""

from __future__ import annotations

from shared.envelope_schema import (
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

__all__ = [
    "CitationSource",
    "ConstraintKind",
    "EnvelopeStatus",
    "ExclusionFlag",
    "ExclusionKind",
    "NutrientConstraint",
    "NutrientEnvelope",
    "NutrientKind",
    "PatientSummary",
    "RuleFire",
]
