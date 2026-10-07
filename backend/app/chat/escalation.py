"""Pattern-based escalation filter for out-of-scope chat requests.

CareLoop chat answers *nutrition-guidance* questions only. Anything outside
that envelope is escalated to a clinician rather than answered:

* **emergency** symptoms (chest pain, breathing trouble, stroke signs, ...) —
  advise urgent care immediately;
* **diagnosis** requests ("do I have ...", "what's wrong with me");
* **medication / dosing changes** (start/stop/adjust prescriptions);
* **out-of-scope topics** (pregnancy, dialysis, paediatrics, cancer treatment
  and other non-nutrition clinical domains).

The filter is deliberately conservative: false-positive escalations are safe,
false-negative answers are not. It is deterministic (regex only, no model).
"""

from __future__ import annotations

import re

__all__ = ["check", "CATEGORIES"]

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
        r"severe (bleeding|dizziness|headache)",
    ],
    "medication_change": [
        r"(stop|start|skip|quit)\s+(taking\s+|my\s+|the\s+)*(medic\w*|pills?|tablets?|capsules?|dose)",
        r"(double|halve|triple) (my )?(dose|dosage|medic\w*|metformin|insulin)",
        r"(increase|reduce|lower|raise|adjust|change) (my )?(dose|dosage|medic\w*)",
        r"how much (metformin|insulin|medicine|medication|\w+ ?\w*) should i take",
        r"\bprescrib\w*",
        r"dos(e|age) of (my )?(metformin|insulin|medic\w*|tablets?|pills?)",
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
        r"my (child|baby|toddler|kid|son|daughter)",
        r"paediatric|pediatric",
    ],
}

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for category, patterns in _CATEGORIES.items()
}

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
    """Return ``{"escalate": bool, "reason": str|None, "category": str|None}``."""
    text = str(question or "")
    for category in CATEGORIES:
        for pattern in _COMPILED[category]:
            if pattern.search(text):
                return {
                    "escalate": True,
                    "reason": _REASONS[category],
                    "category": category,
                }
    return {"escalate": False, "reason": None, "category": None}