"""Pattern-based escalation filter for out-of-scope chat requests.

Detect configured patterns for requests that should be escalated rather than
answered as nutrition guidance:

* **emergency** symptoms (chest pain, breathing trouble, stroke signs, ...) —
  advise urgent care immediately. Extreme glucose readings belong here too:
  the configured category floor is 350 mg/dL with no upper bound. Readings in
  mmol/L use the standard conversion;
* **diagnosis** requests ("do I have ...", "what's wrong with me");
* **medication / dosing changes** (start/stop/adjust prescriptions);
* **out-of-scope topics** (pregnancy, dialysis, paediatrics, cancer treatment
  and other non-nutrition clinical domains).

The regex filter prioritizes escalation when a configured safety pattern matches.
No match is not proof that a question is safe or in scope; this is not a clinical
classifier. Matching is deterministic and uses no model.
"""

from __future__ import annotations

import re

__all__ = ["CATEGORIES", "check"]

# Drug / medication vocabulary for medication-change detection. Specific
# agents commonly managed in CKD/T2D care plus generic medication words, so
# e.g. "should I stop taking metformin?" or "can I skip my insulin today?"
# are escalated even though no generic word appears.
_DRUGS = (
    r"(?:metformin|insulin|lisinopril|enalapril|losartan|valsartan|"
    r"dapagliflozin|empagliflozin|furosemide|spironolactone|"
    r"hydrochlorothiazide|warfarin|amlodipine|atorvastatin|sevelamer|"
    r"medic\w*|medication|medicine|pills?|tablets?|capsules?|doses?|dosage)"
)

_CATEGORIES: dict[str, list[str]] = {
    "emergency": [
        r"chest pain",
        r"can'?t breathe",
        r"cannot breathe",
        r"short(ness)? of breath",
        r"call (an )?ambulance",
        r"call (999|911|995)",
        r"feeling faint",
        r"(fainted|passed out)",
        r"numb(ness)? on one side",
        r"slurred speech",
        r"slurring (my |his |her |their )?speech",
        r"speech (is |has |has been )?slurred",
        r"severe (bleeding|dizziness|headache)",
        # Metabolic emergencies: ketoacidosis signs and extreme glucose reads.
        r"keto?acidosis",
        r"\bketones?\b",
        (
            r"(dizzy|dizziness|light.?headed)\W{0,20}(and|with)\W{0,10}"
            r"(vomit\w*|nausea|confusion|ketone\w*|high sugars?)"
        ),
    ],
    "medication_change": [
        rf"(stop|start|skip|quit)\s+(?:taking\s+|my\s+|the\s+|to\s+)*{_DRUGS}",
        rf"(double|halve|triple)\s+(my\s+|the\s+)?(?:dose|dosage|{_DRUGS})",
        (
            rf"(increase|reduce|lower|raise|adjust|change)\s+(my\s+|the\s+)?"
            rf"(?:dose|dosage|{_DRUGS})"
        ),
        r"how much (metformin|insulin|medicine|medication|\w+ ?\w*) should i take",
        r"\bprescrib\w*",
        rf"dos(e|age) of (my )?(metformin|insulin|{_DRUGS})",
        r"(switch|swap) (to |my )?(another |my )?medic\w*",
    ],
    "diagnosis": [
        r"do i have",
        r"what('?s| is) wrong with me",
        r"\bdiagnos\w*",
        r"what disease",
        r"what condition (do i|am i)",
        r"am i at risk of",
        r"is it (cancer|serious|something bad)",
    ],
    "out_of_scope": [
        r"pregnan\w*",
        r"\bdialysis\b",
        r"chemotherapy",
        r"cancer treatment",
        r"my (child|baby|toddler|kid|son|daughter)\b",
        r"paediatric|pediatric",
    ],
}

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for category, patterns in _CATEGORIES.items()
}

# Preserve the configured direct-reading and "above/over" floors. Unitless
# legacy readings mean mg/dL; explicit mmol/L readings use the same policy.
_GLUCOSE_READING = re.compile(
    r"\b(?:blood\s+sugars?|blood\s+glucose|glucose|sugars?)\b"
    r"(?:\s+(?:is|are|was|were|of|at|around|about|reading))*\s*"
    r"(?:(above|over)\s+)?(\d+(?:\.\d+)?)\b\s*"
    r"(mmol\s*[/ ]\s*l|mg\s*[/ ]\s*dl)?",
    re.IGNORECASE,
)
_GLUCOSE_EMERGENCY_MGDL = 350.0
_GLUCOSE_ABOVE_EMERGENCY_MGDL = 300.0
_MMOL_TO_MGDL = 18.0


def _extreme_glucose_reading(text: str) -> bool:
    """Match the configured emergency glucose category without an upper cap."""
    for comparator, value, unit in _GLUCOSE_READING.findall(text):
        reading = float(value)
        if "mmol" in unit.lower():
            reading *= _MMOL_TO_MGDL
        floor = (_GLUCOSE_ABOVE_EMERGENCY_MGDL if comparator
                 else _GLUCOSE_EMERGENCY_MGDL)
        if reading >= floor:
            return True
    return False

_REASONS = {
    "emergency": (
        "This may be a medical emergency. Please contact emergency services or "
        "urgent care immediately."
    ),
    "medication_change": (
        "Questions about starting, stopping or changing medication and doses "
        "must go through your clinician or pharmacist."
    ),
    "diagnosis": (
        "CareLoop cannot provide diagnoses. Please discuss symptoms and "
        "diagnosis with your clinician."
    ),
    "out_of_scope": (
        "This topic is outside CareLoop's nutrition-guidance scope and needs "
        "a clinician."
    ),
}

# Scan order: most safety-critical first.
CATEGORIES = ["emergency", "medication_change", "diagnosis", "out_of_scope"]


def check(question: str) -> dict[str, object]:
    """Return the first matching safety category in CATEGORIES order.

    Result keys are ``escalate``, ``reason``, and ``category``. With no match,
    return False and null reason/category; downstream grounding still applies.
    """
    for category in CATEGORIES:
        for pattern in _COMPILED[category]:
            if pattern.search(question):
                return {
                    "escalate": True,
                    "reason": _REASONS[category],
                    "category": category,
                }
        if category == "emergency" and _extreme_glucose_reading(question):
            return {
                "escalate": True,
                "reason": _REASONS[category],
                "category": category,
            }
    return {"escalate": False, "reason": None, "category": None}
