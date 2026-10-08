"""CareLoop canonical schemas.

Single source of truth for the contracts that pass between modules:
rules engine -> clinician gate -> optimiser -> meal plan -> RAG chat -> UI.

Import anywhere in the codebase. Pure data models, no side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ----------------------------------------------------------------------------
# Enumerations
# ----------------------------------------------------------------------------


class EnvelopeStatus(str, Enum):
    """Lifecycle states of a nutrient envelope.

    Hard architectural invariant: only APPROVED envelopes may be consumed by the
    optimiser or personal target guidance. PROPOSED, EDITED, and REJECTED
    envelopes do not authorize live downstream use.
    """

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"  # clinician edited the proposal, awaiting re-confirm


class ConstraintKind(str, Enum):
    """Per-nutrient target/ceiling/floor."""

    TARGET = "target"      # desired value (soft)
    MIN = "min"            # desired floor (soft)
    MAX = "max"            # ceiling (hard ceiling when present)


class NutrientKind(str, Enum):
    ENERGY_KCAL = "energy_kcal"
    PROTEIN_G = "protein_g"
    SODIUM_MG = "sodium_mg"
    POTASSIUM_MG = "potassium_mg"
    PHOSPHORUS_MG = "phosphorus_mg"
    CARBS_G = "carbs_g"
    FAT_G = "fat_g"
    SAT_FAT_G = "sat_fat_g"
    FIBER_G = "fiber_g"
    SUGAR_G = "sugar_g"


class ExclusionKind(str, Enum):
    INGREDIENT = "ingredient"
    DISH_CATEGORY = "dish_category"
    MACRO_PATTERN = "macro_pattern"  # e.g. "very-low-carb"
    DIET_PATTERN = "diet_pattern"    # e.g. "high-sodium"


# ----------------------------------------------------------------------------
# Reference models
# ----------------------------------------------------------------------------


class CitationSource(BaseModel):
    """Inline citation attached to every fired rule and envelope."""

    model_config = ConfigDict(extra="forbid")

    guideline: str = Field(..., description="e.g. 'KDIGO 2024' or 'ADA Standards of Care 2026'")
    section: str = Field(..., description="Section reference within the guideline, e.g. 'Chapter 3.2'")
    rule_id: str = Field(..., description="Stable ID assigned to the rule in the rule spec")
    url: Optional[str] = Field(default=None, description="Public URL or local file path")
    verbatim_quote: Optional[str] = Field(
        default=None,
        description="Optional direct quote (kept short, with ellipsis as needed)",
    )


# ----------------------------------------------------------------------------
# Envelope
# ----------------------------------------------------------------------------


class ConstraintProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nutrient: NutrientKind
    kind: ConstraintKind
    value: float
    unit: str
    envelope_id: str
    version: int
    author: str
    citation: CitationSource


class NutrientConstraint(BaseModel):
    """Per-nutrient target/ceiling/floor for a 24-hour plan."""

    model_config = ConfigDict(extra="forbid")

    nutrient: NutrientKind
    kind: ConstraintKind
    value: float = Field(..., ge=0)
    unit: str = Field(..., description="Canonical unit, e.g. 'mg', 'g', 'kcal'")
    provenance: Optional[ConstraintProvenance] = None

    @field_validator("unit")
    @classmethod
    def _unit_matches_nutrient(cls, v: str, info) -> str:
        canonical = {
            NutrientKind.ENERGY_KCAL: "kcal",
            NutrientKind.PROTEIN_G: "g",
            NutrientKind.SODIUM_MG: "mg",
            NutrientKind.POTASSIUM_MG: "mg",
            NutrientKind.PHOSPHORUS_MG: "mg",
            NutrientKind.CARBS_G: "g",
            NutrientKind.FAT_G: "g",
            NutrientKind.SAT_FAT_G: "g",
            NutrientKind.FIBER_G: "g",
            NutrientKind.SUGAR_G: "g",
        }
        n = info.data.get("nutrient")
        if n is not None and canonical.get(n) != v:
            raise ValueError(f"unit {v!r} does not match canonical {canonical.get(n)!r} for {n}")
        return v


class ExclusionFlag(BaseModel):
    """Hard exclusions produced by rules (ingredients, dish categories, patterns)."""

    model_config = ConfigDict(extra="forbid")

    kind: ExclusionKind
    value: str = Field(..., description="Matchable value: ingredient name, category, or pattern string")
    reason: str = Field(..., description="Human-readable explanation")
    citation: CitationSource


class RuleFire(BaseModel):
    """A single rule firing — one row of the explainability trace."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    fired_at: datetime
    patient_summary: str = Field(..., description="Conditions matched, e.g. 'CKD stage 4 + K+ = 5.4'")
    action_summary: str = Field(..., description="What was set or asserted, e.g. 'Na ceiling = 2000 mg/d'")
    priority: int = Field(..., ge=0, description="Higher wins on conflicts")
    citation: CitationSource


class PatientSummary(BaseModel):
    """Minimal patient descriptors needed to explain an envelope.

    Full patient profile lives elsewhere; this is the audit-friendly subset
    frozen with each envelope so traces remain readable months later.
    """

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    age: int = Field(..., ge=0, le=130)
    sex: Literal["F", "M", "X"]
    weight_kg: float = Field(..., gt=0)
    diagnoses: list[str] = Field(
        default_factory=list,
        description="e.g. ['T2D', 'HTN', 'CKD_stage_3']",
    )
    egfr: Optional[float] = Field(default=None, ge=0)
    serum_k_meq_l: Optional[float] = Field(default=None, alias="serum_K_meq_L")
    serum_po4_mg_dl: Optional[float] = Field(default=None, alias="serum_PO4_mg_dL")
    meds: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NutrientEnvelope(BaseModel):
    """The full nutrient envelope contract.

    Live planning requires approval and scope eligibility. Lifecycle services
    enforce transitions; HTTP dependencies enforce downstream access.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_id: str
    patient_id: str
    status: EnvelopeStatus = EnvelopeStatus.PROPOSED
    version: int = Field(default=1, ge=1, description="Content version; incremented by clinician edits")
    lifecycle_revision: int = Field(default=0, ge=0, description="Concurrency token; incremented on every durable lifecycle update")
    scope_eligible: bool = Field(default=True, description="Proposal eligibility, independent of editable notes and lifecycle status")

    patient_snapshot: PatientSummary
    targets: list[NutrientConstraint]
    exclusions: list[ExclusionFlag] = Field(default_factory=list)

    fired_rules: list[RuleFire] = Field(default_factory=list)
    citations: list[CitationSource] = Field(default_factory=list)
    priority_basis: str = Field(
        ...,
        description="Human-readable conflict priority used, e.g. 'CKD > HTN > T2D on sodium'",
    )

    proposed_by: str = Field(default="rules-engine")
    proposed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_scope_eligibility(cls, value):
        """Read old snapshots conservatively without changing their stored JSON."""
        if isinstance(value, dict) and "scope_eligible" not in value:
            value = dict(value)
            value["scope_eligible"] = not (
                value.get("status") == "REJECTED"
                or "careloop_eligible=false" in (value.get("notes") or "")
                or "auto_envelope_suppressed=true" in (value.get("notes") or "")
            )
        return value

    def is_ready_for_optimisation(self) -> bool:
        """Architectural invariant check (also enforced server-side)."""
        return self.status == EnvelopeStatus.APPROVED and self.scope_eligible and bool(self.targets)
