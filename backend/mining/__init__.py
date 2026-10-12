"""CareLoop knowledge-discovery modules.

Modules:
    clustering      - patient cohort clustering (k-means + silhouette)
    substitutions   - food substitution engine (v1 nutrient distance, v2 ranked)
    trends          - longitudinal lab trend detection (Theil-Sen slopes)

Default data paths resolve ``<repo>/data/`` from module locations, independent
of the working directory. Explicit relative paths remain relative to the caller.
"""

from backend.mining import clustering, substitutions, trends

__all__ = ["clustering", "substitutions", "trends"]
