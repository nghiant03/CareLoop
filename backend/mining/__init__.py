"""Cohort clustering, lab trends, and dish substitutions.

Default data paths are installation-relative. Explicit relative paths use cwd.
"""

from backend.mining import clustering, substitutions, trends

__all__ = ["clustering", "substitutions", "trends"]
