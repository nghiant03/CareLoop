"""Canonical envelope, patient-snapshot, and rule-trace data contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnvelopeStatus(str, Enum):
    """Lifecycle states of a nutrient envelope."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


class ConstraintKind(str, Enum):
    """Daily constraint semantics: soft TARGET/MIN aims and hard MAX ceilings."""

    TARGET = "target"
    MIN = "min"
    MAX = "max"


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
    MACRO_PATTERN = "macro_pattern"
    DIET_PATTERN = "diet_pattern"


class CitationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guideline: str = Field(..., description="e.g. 'KDIGO 2024' or 'ADA Standards of Care 2026'")
    section: str = Field(..., description="Section reference within the guideline, e.g. 'Chapter 3.2'")
    rule_id: str = Field(..., description="Stable ID assigned to the rule in the rule spec")
    url: str | None = Field(default=None, description="Public URL or local file path")
    verbatim_quote: str | None = Field(
        default=None,
        description="Optional direct quote",
    )


class ConstraintProvenance(BaseModel):
    """Author and citation for one exact constraint value in an envelope version."""

    model_config = ConfigDict(extra="forbid")

    nutrient: NutrientKind
    kind: ConstraintKind
    value: float = Field(..., allow_inf_nan=False, description="Finite value of the attributed constraint")
    unit: str
    envelope_id: str
    version: int
    author: str
    citation: CitationSource


_CANONICAL_UNITS = {
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


def _add_unit_schema(schema: dict) -> None:
    """Mirror the Python unit validator without duplicating its nutrient map."""
    schema["allOf"] = [
        {"if": {"properties": {"nutrient": {"const": nutrient.value}},
                "required": ["nutrient"]},
         "then": {"properties": {"unit": {"const": unit}}}}
        for nutrient, unit in _CANONICAL_UNITS.items()
    ]


class NutrientConstraint(BaseModel):
    """Daily nutrient aim or ceiling, validated in its nutrient's canonical unit."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_add_unit_schema)

    nutrient: NutrientKind
    kind: ConstraintKind
    value: float = Field(..., ge=0, allow_inf_nan=False, description="Finite daily nutrient aim or ceiling")
    unit: str = Field(..., description="Canonical unit, e.g. 'mg', 'g', 'kcal'")
    provenance: ConstraintProvenance | None = None

    @field_validator("unit")
    @classmethod
    def _unit_matches_nutrient(cls, v: str, info) -> str:
        n = info.data.get("nutrient")
        if n is not None and _CANONICAL_UNITS.get(n) != v:
            raise ValueError(f"unit {v!r} does not match canonical {_CANONICAL_UNITS.get(n)!r} for {n}")
        return v


class ExclusionFlag(BaseModel):
    """Hard exclusions carried by an envelope, from rules or clinician edits."""

    model_config = ConfigDict(extra="forbid")

    kind: ExclusionKind
    value: str = Field(..., description="Matchable value: ingredient name, category, or pattern string")
    reason: str = Field(..., description="Human-readable explanation")
    citation: CitationSource


class RuleFire(BaseModel):
    """Decision-trace row; a fired rule may lose a conflict and not set the final bound."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    fired_at: datetime
    patient_summary: str = Field(..., description="Conditions matched, e.g. 'CKD stage 4 + K+ = 5.4'")
    action_summary: str = Field(..., description="What was set or asserted, e.g. 'Na ceiling = 2000 mg/d'")
    priority: int = Field(..., ge=0, description="Higher wins on conflicts")
    citation: CitationSource


class PatientSummary(BaseModel):
    """Frozen rule inputs, not a live profile.

    Version 1 snapshots may omit BMI/pregnancy/HbA1c; None means unrecorded, not
    evidence of absence. New engine snapshots emit version 2 with these inputs.
    Reading old snapshots does not upgrade them or reconstruct missing values.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    patient_id: str
    age: int = Field(..., ge=0, le=130)
    sex: Literal["F", "M", "X"]
    weight_kg: float = Field(..., gt=0)
    diagnoses: list[str] = Field(
        default_factory=list,
        description="e.g. ['T2D', 'HTN', 'CKD_stage_3']",
    )
    egfr: float | None = Field(default=None, ge=0)
    serum_k_meq_l: float | None = Field(default=None, alias="serum_K_meq_L")
    serum_po4_mg_dl: float | None = Field(default=None, alias="serum_PO4_mg_dL")
    meds: list[str] = Field(default_factory=list)
    snapshot_version: int = Field(default=1, ge=1)
    bmi: float | None = Field(default=None, ge=0)
    pregnant: bool | None = None
    hba1c_pct: float | None = Field(default=None, ge=0)


class NutrientEnvelope(BaseModel):
    """Clinical constraints and decision history; lifecycle services own transitions.

    Missing ``scope_eligible`` currently defaults to True, including on legacy
    snapshots. This model does not infer scope exclusions from status or notes.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_id: str
    patient_id: str
    status: EnvelopeStatus = EnvelopeStatus.PROPOSED
    version: int = Field(default=1, ge=1, description="Content version, incremented by clinician edits")
    lifecycle_revision: int = Field(default=0, ge=0, description="Concurrency token, incremented on every durable lifecycle update")
    scope_eligible: bool = Field(default=True, description="Proposal eligibility, independent of editable notes and lifecycle status")

    patient_snapshot: PatientSummary
    targets: list[NutrientConstraint]
    exclusions: list[ExclusionFlag] = Field(default_factory=list)

    fired_rules: list[RuleFire] = Field(default_factory=list)
    citations: list[CitationSource] = Field(default_factory=list)
    priority_basis: str = Field(
        ...,
        description="Human-readable conflict priority used.",
    )

    proposed_by: str = Field(default="rules-engine")
    proposed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: str | None = None
    approved_at: datetime | None = None
    notes: str | None = None

    def is_ready_for_optimisation(self) -> bool:
        """Whether approval, scope eligibility, and nonempty targets permit live planning."""
        return self.status == EnvelopeStatus.APPROVED and self.scope_eligible and bool(self.targets)
