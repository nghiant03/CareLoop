"""Cohort clustering for synthetic CKD/T2D patients.

Median-impute available features, drop absent columns, and standardize before
k-means. Fixed ``random_state`` is repeatable within the same numerical environment.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

RANDOM_SEED = 42

FEATURE_NAMES = (
    "age",
    "bmi",
    "hba1c_pct",
    "egfr",
    "serum_K_meq_L",
    "serum_PO4_mg_dL",
    "systolic_bp",
    "diastolic_bp",
)


def _feature_matrix(patients: list[dict], feature_names: list[str]) -> np.ndarray:
    """Build an (n_patients, n_features) matrix, median-imputing Nones."""
    raw: list[list[float | None]] = []
    for p in patients:
        row = [p.get(name) for name in feature_names]
        raw.append([float(v) if v is not None else None for v in row])

    matrix = np.asarray(raw, dtype=float)
    col_median = np.nanmedian(matrix, axis=0)
    nan_rows, nan_cols = np.where(np.isnan(matrix))
    matrix[nan_rows, nan_cols] = col_median[nan_cols]
    return matrix


def _dominant_diagnoses(diagnoses: list[str], top: int = 3) -> list[str]:
    counts = Counter(diagnoses)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ordered[:top]]


def cluster_patients(
    patients: list[dict],
    k_range: tuple[int, int] = (2, 6),
) -> dict:
    """Choose k-means cohorts by highest mean silhouette, preferring smaller k.

    ``patients`` are profile dicts. ``k_range`` is inclusive, restricted to
    2 <= k < patient count. Return k, input-order labels, silhouette, cluster
    profiles, and feature names. Raise ValueError for empty input, no usable
    features or k, or a labeling with too few clusters to score.
    """
    if not patients:
        raise ValueError("cluster_patients requires at least one patient")

    # Keep a feature only if at least one patient has a value for it, so an
    # entirely-absent field does not produce an all-NaN column.
    present = [name for name in FEATURE_NAMES if any(p.get(name) is not None for p in patients)]
    if not present:
        raise ValueError("no usable numeric features found on patients")

    matrix = _feature_matrix(patients, present)
    scaled = StandardScaler().fit_transform(matrix)

    n = len(patients)
    lo, hi = k_range
    candidate_ks = [k for k in range(lo, hi + 1) if 2 <= k <= n - 1]
    if not candidate_ks:
        raise ValueError(f"no valid k in {k_range} for {n} patients")

    best_k, best_labels, best_sil = None, None, -np.inf
    for k in candidate_ks:
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_SEED)
        labels = km.fit_predict(scaled)
        sil = float(silhouette_score(scaled, labels))
        if sil > best_sil:
            best_k, best_labels, best_sil = k, labels, sil

    if best_k is None or best_labels is None:
        raise ValueError("no clustering produced a finite silhouette score")

    profiles = {}
    for cid in sorted(set(best_labels)):
        members = [p for p, lab in zip(patients, best_labels) if lab == cid]
        idx = [i for i, lab in enumerate(best_labels) if lab == cid]
        profiles[int(cid)] = {
            "size": len(members),
            "means": {
                name: round(float(np.mean(matrix[idx, j])), 3)
                for j, name in enumerate(present)
            },
            "dominant_diagnoses": _dominant_diagnoses(
                [d for p in members for d in p.get("diagnoses", [])]
            ),
        }

    return {
        "k": best_k,
        "labels": [int(l) for l in best_labels],
        "silhouette": round(best_sil, 4),
        "profiles": profiles,
        "feature_names": present,
    }
