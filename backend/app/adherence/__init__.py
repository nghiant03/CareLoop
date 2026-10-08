"""Adherence loop: logged meals vs the approved nutrient envelope.

Sub-modules
-----------
- :mod:`store`    — process-local meal-log store (Week 1 prototype pattern).
- :mod:`analysis` — deterministic deviation analysis + trend flags.
"""

from backend.app.adherence import analysis, store

__all__ = ["analysis", "store"]