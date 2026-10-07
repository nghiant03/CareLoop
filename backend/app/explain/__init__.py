"""Explanation view builders — deterministic, pure functions.

Two audiences, one trace:

* :func:`clinician_explanation` — structured audit view: fired rules with
  priorities and guideline links, conflict resolutions (who overrode whom),
  and the resulting constraints with citations.
* :func:`patient_explanation` — plain-language daily targets ("keep salt under
  2 g a day"), short why-bullets from trace citations, no jargon or rule ids
  exposed in the prose.

Both operate on plain dicts (the ``shared/envelope_schema.py`` shapes, as also
mirrored by ``rules/example_trace.json``) so they can be called with either
pydantic models (via ``model_dump()``) or raw JSON.
"""

from backend.app.explain.views import clinician_explanation, patient_explanation

__all__ = ["clinician_explanation", "patient_explanation"]