"""Adherence loop: logged meals vs the approved nutrient envelope.

Sub-modules
-----------
- :mod:`store`    — durable SQLite meal-log store.
- :mod:`analysis` — deterministic deviation analysis + trend flags.
"""

from backend.app.adherence import analysis, store

__all__ = ["analysis", "store"]
