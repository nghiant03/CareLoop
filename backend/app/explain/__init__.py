"""Explanation view builders — deterministic, pure functions.

Two audiences, one trace:

* :func:`clinician_explanation` — structured audit view: fired rules with
  priorities and guideline links, recorded conflict resolutions, separately
  labeled priority overlaps, and resulting constraints with citations.
* :func:`patient_explanation` — plain-language daily targets such as "keep sodium
  under 2 g a day", short why-bullets from trace citations, no jargon or rule ids
  exposed in the prose.

Both accept plain dictionaries shaped according to ``shared/envelope_schema.py``,
also mirrored by ``rules/example_trace.json``. Convert Pydantic models with
``model_dump()`` or pass decoded JSON dictionaries directly.
"""

from backend.app.explain.views import clinician_explanation, patient_explanation

__all__ = ["clinician_explanation", "patient_explanation"]
