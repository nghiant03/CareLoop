"""clipspy fact templates for CareLoop.

Week 1 deliverable (Lane A): the CLIPS ``deftemplate`` layer that mirrors the
canonical pydantic contracts in ``shared/envelope_schema.py``.

Design notes
------------
* This module is deliberately **import-safe**: ``clipspy`` is an optional
  dependency and is *not installed yet* (see rules/README.md). Importing this
  file never requires CLIPS. The engine is created lazily by the caller.
* We only declare templates and pure mapping helpers here. We do **not**
  instantiate ``clips.Environment`` and do **not** assert any facts at import
  time. Week 2 wires these into the real RETE network.
* Template slots map 1:1 onto ``PatientSummary`` and the reference models used
  by ``NutrientConstraint`` / ``ExclusionFlag`` / ``RuleFire`` so that the
  forward-chaining output can be serialised straight back into a
  ``NutrientEnvelope``.

Usage (Week 2, once clipspy is installed)::

    from rules.clipspy_facts import CLIPS_AVAILABLE, load_templates, patient_fact
    env = clips.Environment()
    load_templates(env)
    env.assert_string(patient_fact(patient_summary))   # or env.assert_string(...)
    env.run()
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Optional dependency — never imported eagerly at module scope by callers.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - exercised only when clipspy is installed
    import clips  # type: ignore

    CLIPS_AVAILABLE = True
except Exception:  # ImportError, or any native-library load error
    clips = None  # type: ignore
    CLIPS_AVAILABLE = False


# ---------------------------------------------------------------------------
# CLIPS deftemplates
# ---------------------------------------------------------------------------
# CLIPS symbols cannot contain many punctuation characters, so every enum-like
# slot uses a symbol (e.g. ``ckd_stage_4``) rather than a free string. The
# canonical nutrient/kind/unit values match shared/envelope_schema.py exactly.
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
;; Derived / asserted flags — produced by antecedent rules, consumed by others.
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


# ---------------------------------------------------------------------------
# Pure mapping helpers (no CLIPS required to call these)
# ---------------------------------------------------------------------------
def _sym(value: Any) -> str:
    """Render a Python value as a CLIPS-safe symbol/string token."""
    text = str(value).strip().replace(" ", "_")
    return text


def patient_fact(patient: Any) -> str:
    """Build a CLIPS ``(patient ...)`` fact string from a PatientSummary-like object.

    Accepts either a pydantic ``PatientSummary`` or any object/dict exposing the
    same field names. ``-1.0`` marks an unknown numeric lab.
    """
    if isinstance(patient, dict):
        get = patient.get
    else:
        get = lambda name, default=None: getattr(patient, name, default)  # noqa: E731

    def num(name: str) -> float:
        value = get(name)
        return float(value) if value is not None else -1.0

    diagnoses = " ".join(_sym(d) for d in (get("diagnoses") or []))
    meds = " ".join(_sym(m) for m in (get("meds") or []))
    pregnant = "yes" if get("pregnant") else "no"
    return (
        "(patient "
        f'(patient_id "{get("patient_id")}") '
        f"(age {int(get('age'))}) "
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
    """Build a CLIPS ``(nutrient-constraint ...)`` fact string."""
    return (
        "(nutrient-constraint "
        f"(nutrient {_sym(nutrient)}) "
        f"(kind {_sym(kind)}) "
        f"(value {float(value)}) "
        f"(unit {_sym(unit)}) "
        f'(rule_id "{rule_id}") '
        f"(priority {int(priority)}))"
    )


def exclusion_fact(kind: str, value: str, reason: str, rule_id: str, priority: int) -> str:
    """Build a CLIPS ``(exclusion-flag ...)`` fact string."""
    safe_reason = str(reason).replace('"', "'")
    return (
        "(exclusion-flag "
        f"(kind {_sym(kind)}) "
        f'(value "{value}") '
        f'(reason "{safe_reason}") '
        f'(rule_id "{rule_id}") '
        f"(priority {int(priority)}))"
    )


def load_templates(env: Any) -> None:
    """Compile the CareLoop deftemplates into a live ``clips.Environment``.

    Lazy by design: the caller must have created the environment (and therefore
    installed clipspy) before calling this.
    """
    if not CLIPS_AVAILABLE:
        raise RuntimeError(
            "clipspy is not installed. Install it (pip install clipspy) before "
            "loading CLIPS templates; the rest of the rule spec is usable without it."
        )
    env.build(FACTS_DEFTEMPLATE)


if __name__ == "__main__":  # pragma: no cover
    print("clipspy available:", CLIPS_AVAILABLE)
    print("templates declared:", FACTS_DEFTEMPLATE.count("(deftemplate"))
