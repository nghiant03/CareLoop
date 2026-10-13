"""Hand-built APPROVED benchmark fixtures, not clinical approvals or advice."""

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
)


def _cite(guideline: str, section: str, rule_id: str) -> CitationSource:
    return CitationSource(guideline=guideline, section=section, rule_id=rule_id)


def _exclusion(kind: ExclusionKind, value: str, reason: str, rule_id: str) -> ExclusionFlag:
    return ExclusionFlag(kind=kind, value=value, reason=reason, citation=_cite("KDIGO 2024", "3.2", rule_id))


def _envelope(
    envelope_id: str,
    patient_id: str,
    age: int,
    sex: str,
    weight_kg: float,
    diagnoses: list[str],
    targets: list[NutrientConstraint],
    exclusions: list[ExclusionFlag],
    priority_basis: str,
) -> NutrientEnvelope:
    return NutrientEnvelope(
        envelope_id=envelope_id,
        patient_id=patient_id,
        status=EnvelopeStatus.APPROVED,
        version=1,
        patient_snapshot=PatientSummary(
            patient_id=patient_id,
            age=age,
            sex=sex,  # type: ignore[arg-type]
            weight_kg=weight_kg,
            diagnoses=diagnoses,
        ),
        targets=targets,
        exclusions=exclusions,
        priority_basis=priority_basis,
    )


def ckd_strict() -> NutrientEnvelope:
    """CKD stage 3-4: Na <= 2000, K <= 2600, P <= 900, protein 55-85 g."""
    return _envelope(
        envelope_id="env-bench-ckd-strict",
        patient_id="p-bench-ckd",
        age=64,
        sex="M",
        weight_kg=70.0,
        diagnoses=["CKD_stage_3"],
        targets=[
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1800.0, unit="kcal"),
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.POTASSIUM_MG, kind=ConstraintKind.MAX, value=2600.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.PHOSPHORUS_MG, kind=ConstraintKind.MAX, value=900.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=55.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MAX, value=85.0, unit="g"),
        ],
        exclusions=[
            _exclusion(ExclusionKind.DISH_CATEGORY, "deep_fried", "Fried foods worsen cardiovascular risk", "R-EX-DF"),
            _exclusion(ExclusionKind.INGREDIENT, "coconut milk", "Saturated-fat / cardiovascular risk", "R-EX-COCO"),
        ],
        priority_basis="CKD > CV > general",
    )


def ckd_hyperkalemia() -> NutrientEnvelope:
    """CKD with K+ 5.4 mmol/L: potassium ceiling tightened to 2000 mg."""
    env = ckd_strict()
    return env.model_copy(
        update={
            "envelope_id": "env-bench-ckd-hyperk",
            "patient_id": "p-bench-hyperk",
            "patient_snapshot": env.patient_snapshot.model_copy(
                update={
                    "patient_id": "p-bench-hyperk",
                    "serum_k_meq_l": 5.4,
                    "diagnoses": ["CKD_stage_4"],
                }
            ),
            "targets": [
                NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1800.0, unit="kcal"),
                NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
                NutrientConstraint(nutrient=NutrientKind.POTASSIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
                NutrientConstraint(nutrient=NutrientKind.PHOSPHORUS_MG, kind=ConstraintKind.MAX, value=900.0, unit="mg"),
                NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=55.0, unit="g"),
                NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MAX, value=85.0, unit="g"),
            ],
            "exclusions": env.exclusions
            + [
                _exclusion(
                    ExclusionKind.DIET_PATTERN,
                    "high_potassium",
                    "Serum K+ 5.4 mmol/L: avoid high-potassium dishes",
                    "R-EX-HK",
                )
            ],
            "priority_basis": "Hyperkalemia > CKD > CV",
        }
    )


def t2d_htn() -> NutrientEnvelope:
    """T2D + hypertension: carbs/sugar ceilings plus the Na ceiling."""
    return _envelope(
        envelope_id="env-bench-t2d-htn",
        patient_id="p-bench-t2dhtn",
        age=58,
        sex="F",
        weight_kg=78.0,
        diagnoses=["T2D", "HTN"],
        targets=[
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1800.0, unit="kcal"),
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.CARBS_G, kind=ConstraintKind.MAX, value=220.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.SUGAR_G, kind=ConstraintKind.MAX, value=30.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=50.0, unit="g"),
        ],
        exclusions=[
            _exclusion(ExclusionKind.DISH_CATEGORY, "deep_fried", "Fried foods worsen glycaemic/CV risk", "R-EX-DF"),
        ],
        priority_basis="HTN > T2D",
    )


def t2d_only() -> NutrientEnvelope:
    """T2D only: milder ceilings, no renal limits."""
    return _envelope(
        envelope_id="env-bench-t2d-only",
        patient_id="p-bench-t2d",
        age=52,
        sex="M",
        weight_kg=82.0,
        diagnoses=["T2D"],
        targets=[
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1900.0, unit="kcal"),
            NutrientConstraint(nutrient=NutrientKind.CARBS_G, kind=ConstraintKind.MAX, value=250.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.SUGAR_G, kind=ConstraintKind.MAX, value=35.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.FAT_G, kind=ConstraintKind.MAX, value=90.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=50.0, unit="g"),
        ],
        exclusions=[
            _exclusion(ExclusionKind.DISH_CATEGORY, "dessert", "Desserts spike post-prandial glucose", "R-EX-DES"),
        ],
        priority_basis="T2D",
    )


def build_benchmark_envelopes() -> dict[str, NutrientEnvelope]:
    """The four representative envelopes, keyed by short profile name."""
    return {
        "ckd_strict": ckd_strict(),
        "ckd_hyperkalemia": ckd_hyperkalemia(),
        "t2d_htn": t2d_htn(),
        "t2d_only": t2d_only(),
    }


__all__ = [
    "build_benchmark_envelopes",
    "ckd_hyperkalemia",
    "ckd_strict",
    "t2d_htn",
    "t2d_only",
]
