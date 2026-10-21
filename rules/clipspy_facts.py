"""Reference CLIPS templates and pure fact-rendering helpers.

Mapping helpers remain importable without clipspy. Callers own environments and
load templates explicitly. These reference shapes are not ``rules.engine``'s
active templates. Python assembly supplies nested citations and provenance.
"""

from __future__ import annotations

import re
from typing import Any

# Guard native-library loading so pure mapping helpers remain importable without CLIPS.
try:  # pragma: no cover - exercised only when clipspy is installed
    import clips  # type: ignore

    CLIPS_AVAILABLE = True
except Exception:  # noqa: BLE001  # ImportError, or any native-library load error
    clips = None  # type: ignore
    CLIPS_AVAILABLE = False


# Enum-like slots use symbols; free-text fields use strings. Nutrient/kind/unit
# tokens follow the shared schema, while unknown numeric labs use -1.0.
FACTS_DEFTEMPLATE = r"""
;; ------------------------------------------------------------------
;; CareLoop patient fact — mirrors shared.envelope_schema.PatientSummary
;; ------------------------------------------------------------------
(deftemplate patient
   (slot patient_id (type STRING))
   (slot age (type INTEGER))
   (slot sex (type SYMBOL))                 ; F | M | X
   (slot weight_kg (type FLOAT))
   (multislot diagnoses (type SYMBOL))      ; CKD_stage_4 HTN T2D ...
   (slot egfr (type FLOAT) (default -1.0))  ; -1.0 = unknown
   (slot serum_K_meq_L (type FLOAT) (default -1.0))
   (slot serum_PO4_mg_dL (type FLOAT) (default -1.0))
   (multislot meds (type SYMBOL))           ; ACEi ARB SGLT2i metformin ...
   (slot bmi (type FLOAT) (default -1.0))
   (slot pregnant (type SYMBOL) (default no))
)

;; ------------------------------------------------------------------
;; Derived / asserted flags — retained for explanation views.
;; Open world: any key/value pair can be asserted here.
;; ------------------------------------------------------------------
(deftemplate clinical-flag
   (slot key (type SYMBOL))
   (slot value (type STRING))
   (slot rule_id (type STRING))
)

;; ------------------------------------------------------------------
;; Nutrient constraint — mirrors shared.envelope_schema.NutrientConstraint
;; nutrient/kind/unit use the canonical enum values from the schema.
;; ------------------------------------------------------------------
(deftemplate nutrient-constraint
   (slot nutrient (type SYMBOL))   ; energy_kcal protein_g sodium_mg ...
   (slot kind (type SYMBOL))       ; target | min | max
   (slot value (type FLOAT))
   (slot unit (type SYMBOL))       ; kcal | g | mg
   (slot rule_id (type STRING))
   (slot priority (type INTEGER))
)

;; ------------------------------------------------------------------
;; Exclusion flag — mirrors shared.envelope_schema.ExclusionFlag
;; ------------------------------------------------------------------
(deftemplate exclusion-flag
   (slot kind (type SYMBOL))       ; ingredient | dish_category | macro_pattern | diet_pattern
   (slot value (type STRING))
   (slot reason (type STRING))
   (slot rule_id (type STRING))
   (slot priority (type INTEGER))
)

;; ------------------------------------------------------------------
;; Rule fire — mirrors shared.envelope_schema.RuleFire (the explainability row)
;; ------------------------------------------------------------------
(deftemplate rule-fire
   (slot rule_id (type STRING))
   (slot fired_at (type STRING))   ; ISO-8601 UTC
   (slot patient_summary (type STRING))
   (slot action_summary (type STRING))
   (slot priority (type INTEGER))
   (slot guideline (type STRING))
   (slot section (type STRING))
   (slot url (type STRING))
   (slot verbatim_quote (type STRING))
)

;; ------------------------------------------------------------------
;; Scope gate — a hard stop produced by SCOPE-* rules.
;; ------------------------------------------------------------------
(deftemplate scope-gate
   (slot eligible (type SYMBOL))   ; yes | no
   (slot reason (type STRING))
   (slot rule_id (type STRING))
)
"""


def _sym(value: Any) -> str:
    """Replace spaces with underscores; this is not general CLIPS input escaping."""
    text = str(value).strip().replace(" ", "_")
    return text


def patient_fact(patient: Any) -> str:
    """Build a CLIPS ``(patient ...)`` fact string from a PatientSummary-like object.

    Read CLIPS field names, including ``serum_K_meq_L`` and ``serum_PO4_mg_dL``,
    from a dict or object. Pass canonical models as ``model_dump(by_alias=True)``
    because their Python lab attributes use different names. Missing numeric fields
    become ``-1.0``. Values must be trusted: quoted fields are not escaped.
    """
    if isinstance(patient, dict):
        get = patient.get
    else:
        get = lambda name, default=None: getattr(patient, name, default)

    def num(name: str) -> float:
        value = get(name)
        return float(value) if value is not None else -1.0

    diagnoses = " ".join(_sym(d) for d in (get("diagnoses") or []))
    meds = " ".join(_sym(m) for m in (get("meds") or []))
    pregnant = "yes" if get("pregnant") else "no"
    return (
        "(patient "
        f'(patient_id "{get("patient_id")}") '
        f"(age {int(get('age') or 0)}) "
        f"(sex {_sym(get('sex'))}) "
        f"(weight_kg {num('weight_kg')}) "
        f"(diagnoses {diagnoses}) "
        f"(egfr {num('egfr')}) "
        f"(serum_K_meq_L {num('serum_K_meq_L')}) "
        f"(serum_PO4_mg_dL {num('serum_PO4_mg_dL')}) "
        f"(meds {meds}) "
        f"(bmi {num('bmi')}) "
        f"(pregnant {pregnant}))"
    )


def nutrient_constraint_fact(nutrient: str, kind: str, value: float, unit: str,
                             rule_id: str, priority: int) -> str:
    """Build a reference constraint fact from trusted tokens and an unescaped rule ID."""
    return (
        "(nutrient-constraint "
        f"(nutrient {_sym(nutrient)}) "
        f"(kind {_sym(kind)}) "
        f"(value {float(value)}) "
        f"(unit {_sym(unit)}) "
        f'(rule_id "{rule_id}") '
        f"(priority {priority}))"
    )


def exclusion_fact(kind: str, value: str, reason: str, rule_id: str, priority: int) -> str:
    """Build a reference exclusion fact from trusted values.

    Replace double quotes in the reason with apostrophes. Other quoted fields
    and backslashes are not escaped. This is not a general input serializer.
    """
    safe_reason = reason.replace('"', "'")
    return (
        "(exclusion-flag "
        f"(kind {_sym(kind)}) "
        f'(value "{value}") '
        f'(reason "{safe_reason}") '
        f'(rule_id "{rule_id}") '
        f"(priority {priority}))"
    )


def load_templates(env: Any) -> None:
    """Compile the CareLoop deftemplates into a live ``clips.Environment``.

    The caller owns the environment. Missing clipspy raises RuntimeError.
    """
    if not CLIPS_AVAILABLE:
        raise RuntimeError(
            "clipspy is not installed. Install it (pip install clipspy) before "
            "loading CLIPS templates; the rest of the rule spec is usable without it."
        )
    # Each reference template ends with a standalone closing parenthesis.
    # Environment.build accepts one construct, not the complete template block.
    for construct in re.findall(r"^\(deftemplate .*?^\)", FACTS_DEFTEMPLATE, re.MULTILINE | re.DOTALL):
        env.build(construct)


if __name__ == "__main__":  # pragma: no cover
    print("clipspy available:", CLIPS_AVAILABLE)
    print("templates declared:", FACTS_DEFTEMPLATE.count("(deftemplate"))
