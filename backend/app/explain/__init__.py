"""Pure clinician and patient views of envelope and trace dictionaries.

Convert canonical models with ``model_dump()`` before passing them to builders.
"""

from backend.app.explain.views import clinician_explanation, patient_explanation

__all__ = ["clinician_explanation", "patient_explanation"]
