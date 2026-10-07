"""CareLoop knowledge-discovery modules.

Modules:
    clustering      - patient cohort clustering (k-means + silhouette)
    substitutions   - food substitution engine (v1 nutrient distance, v2 ranked)
    trends          - longitudinal lab trend detection (Theil-Sen slopes)

Data lives in ``<repo>/data/``; every loader resolves the repo root from this
file's location, so paths work from any working directory.
"""

from backend.mining import clustering, substitutions, trends  # noqa: F401

__all__ = ["clustering", "substitutions", "trends"]