from __future__ import annotations

import re

__all__ = ["CATEGORIES", "check"]

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

# Unitless legacy glucose readings use milligrams per deciliter.
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

CATEGORIES = ["emergency", "medication_change", "diagnosis", "out_of_scope"]


def check(question: str) -> dict[str, object]:
    """Check categories in safety priority order before grounding."""
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
