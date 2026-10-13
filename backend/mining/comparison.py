"""Compare clustering, lab-trend estimators, and substitution rankings.

Run with ``.venv/bin/python -m backend.mining.comparison`` to write
``COMPARISON.md``. Fixed seeds and shared production input helpers make
comparisons repeatable within the same numerical environment.

Historical scorers remain explicit alternatives, not replicas of production.
Synthetic trend scenarios test detection and false alarms. Fixture patient
series illustrate behavior but do not establish clinical validity.
"""

from __future__ import annotations

import itertools
import json
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import kendalltau
from sklearn.cluster import HDBSCAN, KMeans  # type: ignore[missing-module-attribute]
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from . import clustering, substitutions, trends

_REPO_ROOT = Path(__file__).resolve().parents[2]
PATIENTS_PATH = _REPO_ROOT / "data" / "patients.json"
COMPARISON_MD_PATH = Path(__file__).resolve().parent / "COMPARISON.md"

SEED = 42
STABILITY_SEEDS = (0, 1, 2, 3, 4)
BOOTSTRAP_DRAWS = 10
BOOTSTRAP_SIZE = 15  # of 20 patients
BOOTSTRAP_SEED = 7

K_RANGE = (2, 6)
HDBSCAN_MIN_CLUSTER_SIZES = (3, 4, 5, 6)
GMM_COVARIANCE_TYPES = ("diag", "full")



def _f(value: float | None, nd: int = 3) -> str:
    """Format a float for markdown; ``None`` -> n/a."""
    if value is None:
        return "n/a"
    return f"{value:.{nd}f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return f"{head}\n{sep}\n{body}"


# Clustering comparison


def _standardised_features(patients: list[dict]) -> tuple[np.ndarray, list[str]]:
    """Reuse clustering.py's feature extraction + standardisation."""
    present = [
        name
        for name in clustering.FEATURE_NAMES
        if any(p.get(name) is not None for p in patients)
    ]
    matrix = clustering._feature_matrix(patients, present)
    scaled = StandardScaler().fit_transform(matrix)
    return np.asarray(scaled), present


def _kmeans_labels(X: np.ndarray, config: dict, seed: int) -> np.ndarray:
    km = KMeans(n_clusters=config["k"], n_init=10, random_state=seed)
    return np.asarray(km.fit_predict(X))


def _gmm_labels(X: np.ndarray, config: dict, seed: int) -> np.ndarray:
    with warnings.catch_warnings():
        # tiny-n GMM fits can emit convergence warnings; irrelevant here
        warnings.simplefilter("ignore")
        gm = GaussianMixture(
            n_components=config["k"],
            covariance_type=config["covariance_type"],
            n_init=5,
            random_state=seed,
        )
        return np.asarray(gm.fit_predict(X))


def _hdbscan_labels(X: np.ndarray, config: dict, seed: int) -> np.ndarray:
    # sklearn's HDBSCAN is deterministic; the seed is accepted for a uniform
    # fitter signature and ignored.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # sklearn FutureWarning re `copy`
        return np.asarray(HDBSCAN(min_cluster_size=config["min_cluster_size"]).fit_predict(X))


def _cluster_metrics(X: np.ndarray, labels: np.ndarray, drop_noise: bool) -> dict:
    """Silhouette / Davies-Bouldin / Calinski-Harabasz for a labeling.

    For HDBSCAN (``drop_noise=True``) noise points (label -1) are excluded
    before scoring — the standard practice — and counted separately.
    """
    labels = np.asarray(labels)
    noise = int((labels == -1).sum()) if drop_noise else 0
    if drop_noise:
        mask = labels != -1
        X_use, labels_use = X[mask], labels[mask]
    else:
        X_use, labels_use = X, labels

    n_clusters = len(set(labels_use.tolist()))
    out: dict = {
        "silhouette": None,
        "davies_bouldin": None,
        "calinski_harabasz": None,
        "n_clusters": n_clusters,
        "noise_points": noise,
    }
    if n_clusters < 2 or n_clusters >= len(labels_use):
        return out
    out["silhouette"] = float(silhouette_score(X_use, labels_use))
    out["davies_bouldin"] = float(davies_bouldin_score(X_use, labels_use))
    out["calinski_harabasz"] = float(calinski_harabasz_score(X_use, labels_use))
    return out


def _mean_pairwise_ari(label_sets: list[np.ndarray]) -> float:
    pairs = list(itertools.combinations(label_sets, 2))
    return float(np.mean([adjusted_rand_score(a, b) for a, b in pairs]))


def _bootstrap_stability(
    fitter, config: dict, X: np.ndarray, ref_labels: np.ndarray
) -> float:
    """Mean ARI between the full-data fit and refits on random subsamples."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    aris = []
    for _ in range(BOOTSTRAP_DRAWS):
        idx = np.sort(rng.choice(len(X), size=BOOTSTRAP_SIZE, replace=False))
        sub_labels = fitter(X[idx], config, SEED)
        aris.append(adjusted_rand_score(ref_labels[idx], sub_labels))
    return float(np.mean(aris))


def compare_clustering(patients: list[dict]) -> dict:
    X, features = _standardised_features(patients)
    lo, hi = K_RANGE
    ks = [k for k in range(lo, hi + 1) if 2 <= k <= len(patients) - 1]

    methods: dict[str, dict[str, Any]] = {
        "k-means": {"fitter": _kmeans_labels, "drop_noise": False, "grid": []},
        "gmm": {"fitter": _gmm_labels, "drop_noise": False, "grid": []},
        "hdbscan": {"fitter": _hdbscan_labels, "drop_noise": True, "grid": []},
    }
    grids: dict[str, list[dict[str, Any]]] = {
        "k-means": [{"k": k} for k in ks],
        "gmm": [{"k": k, "covariance_type": cov} for k in ks for cov in GMM_COVARIANCE_TYPES],
        "hdbscan": [{"min_cluster_size": m} for m in HDBSCAN_MIN_CLUSTER_SIZES],
    }

    for name, spec in methods.items():
        fitter = spec["fitter"]
        drop_noise = spec["drop_noise"]
        scored = []
        for config in grids[name]:
            labels = fitter(X, config, SEED)
            metrics = _cluster_metrics(X, labels, drop_noise)
            scored.append((config, metrics, labels))
        spec["grid"] = [
            {"config": cfg, **{k: v for k, v in m.items()}} for cfg, m, _ in scored
        ]

        # pick best config: highest silhouette among usable configs; HDBSCAN
        # falls back to the config with the fewest noise points if none is
        # usable (fewer than 2 non-noise clusters).
        usable = [
            (cfg, m, labels)
            for cfg, m, labels in scored
            if m["silhouette"] is not None
            and (not drop_noise or m["noise_points"] <= 0.5 * len(patients))
        ]
        if usable:
            best_cfg, best_m, best_labels = max(
                usable, key=lambda t: (t[1]["silhouette"], -t[0].get("k", 0))
            )
        else:
            best_cfg, best_m, best_labels = min(
                scored, key=lambda t: (t[1]["noise_points"], -t[1]["n_clusters"])
            )

        # seed stability: refit with different random_state values
        seed_labels = [fitter(X, best_cfg, seed) for seed in STABILITY_SEEDS]
        seed_ari = _mean_pairwise_ari(seed_labels)
        # bootstrap subsample stability (applies to every method, including
        # the seed-invariant HDBSCAN)
        boot_ari = _bootstrap_stability(fitter, best_cfg, X, best_labels)

        chosen = dict(best_cfg)
        if name == "gmm":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gm = GaussianMixture(
                    n_components=chosen["k"],
                    covariance_type=chosen["covariance_type"],
                    n_init=5,
                    random_state=SEED,
                )
                gm.fit(X)
                chosen["bic"] = round(float(gm.bic(X)), 2)

        spec["result"] = {
            "chosen_config": chosen,
            **best_m,
            "seed_stability_ari": round(seed_ari, 4),
            "bootstrap_stability_ari": round(boot_ari, 4),
            "seed_invariant": name == "hdbscan",
        }

    # cluster-count behaviour
    gmm_bic: dict[str, dict[int, float]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for cov in GMM_COVARIANCE_TYPES:
            per_k = {}
            for k in ks:
                gm = GaussianMixture(
                    n_components=k, covariance_type=cov, n_init=5, random_state=SEED
                )
                gm.fit(X)
                per_k[k] = round(float(gm.bic(X)), 2)
            gmm_bic[cov] = per_k

    hdbscan_noise = {}
    for m in HDBSCAN_MIN_CLUSTER_SIZES:
        labels = _hdbscan_labels(X, {"min_cluster_size": m}, SEED)
        hdbscan_noise[m] = {
            "noise_points": int((labels == -1).sum()),
            "n_clusters": len({l for l in labels.tolist() if l != -1}),
        }

    kmeans_sil_by_k = {
        g["config"]["k"]: g["silhouette"] for g in methods["k-means"]["grid"]
    }

    results: dict[str, Any] = {
        "n_patients": len(patients),
        "features": features,
        "methods": {name: spec["result"] for name, spec in methods.items()},
        "kmeans_silhouette_by_k": kmeans_sil_by_k,
        "gmm_bic_by_k": gmm_bic,
        "hdbscan_noise_by_min_cluster_size": hdbscan_noise,
    }
    results["metric_winners"] = _clustering_winners(results)
    results["recommendation_method"], results["recommendation"] = _clustering_verdict(
        results
    )
    return results


def _clustering_winners(results: dict) -> dict:
    m = results["methods"]
    higher = [
        ("silhouette", max(m, key=lambda n: m[n]["silhouette"] or -np.inf)),
        ("calinski_harabasz", max(m, key=lambda n: m[n]["calinski_harabasz"] or -np.inf)),
        ("seed_stability_ari", max(m, key=lambda n: m[n]["seed_stability_ari"])),
        ("bootstrap_stability_ari", max(m, key=lambda n: m[n]["bootstrap_stability_ari"])),
    ]
    lower = [("davies_bouldin", min(m, key=lambda n: m[n]["davies_bouldin"] or np.inf))]
    return {metric: winner for metric, winner in higher + lower}


def _clustering_verdict(results: dict) -> tuple[str, str]:
    wins: dict[str, int] = {name: 0 for name in results["methods"]}
    for winner in results["metric_winners"].values():
        wins[winner] += 1
    best = max(wins, key=lambda n: (wins[n], n))

    hd = results["methods"]["hdbscan"]
    noise = hd["noise_points"]
    noise_pct = 100.0 * noise / results["n_patients"]

    rationale = {
        "k-means": (
            "k-means wins most internal metrics on this 20-patient cohort: it "
            "uses every patient (no noise points), is fully deterministic, and "
            "its chosen k is directly interpretable as the number of care "
            "cohorts. HDBSCAN marks "
            f"{noise}/{results['n_patients']} patients ({noise_pct:.0f}%) as "
            "noise at this sample size — too few points for density-based "
            "clusters — and GMM's covariance estimates are over-parameterised "
            "for n=20 (its BIC is useful as a k-selection cross-check only)."
        ),
        "gmm": (
            "GMM wins most internal metrics here, but with n=20 its "
            "covariance estimates are fragile (many parameters per point) and "
            "its soft assignments are harder to explain to clinicians than "
            "hard cohort labels. Treat GMM's BIC as a k-selection cross-check "
            "rather than the production clusterer."
        ),
        "hdbscan": (
            "HDBSCAN wins most internal metrics, but note "
            f"{noise}/{results['n_patients']} patients are left as noise and "
            "the metrics exclude them — the 'clean' scores come from scoring "
            "only the dense core. With 20 patients, k-means remains the more "
            "honest default; revisit HDBSCAN when the cohort grows."
        ),
    }
    return best, rationale[best]


# Trend-estimator comparison


def _ols_slope(y: list[float]) -> float:
    values = np.asarray(y, dtype=float)
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, values, 1)[0])


# Reuse the production EWMA estimator so the study measures the same slope
# used for trend de-escalation.


ESTIMATORS: dict[str, Callable[[list[float]], float]] = {
    "theil-sen": trends._theil_sen_slope,
    "ols": _ols_slope,
    "ewma": trends._ewma_slope,
}


def _would_flag(series: list[float], slope: float, cfg: dict) -> bool:
    """Apply the slope/projection rule to a monthly series with at least three points.

    Unlike ``trends.detect_trends``, this study helper does not handle dated
    urgent observations or assign EWMA-adjusted severity.
    """
    if len(series) < trends._MIN_SERIES_LEN:
        return False
    latest = series[-1]
    projected = latest + 3.0 * slope
    slope_trigger = slope > trends._SLOPE_TRIGGER
    crossing = projected >= cfg["flag"] and latest < cfg["flag"]
    return bool(slope_trigger or crossing)


# name -> (truth: should the FULL 6-month series be flagged?, monthly path)
# False-truth scenarios double as false-positive probes measured at the end
# of the window; `plateau` specifically tests whether an estimator keeps
# crying wolf after a rise has stopped (adaptivity).
_SCENARIOS: dict[str, dict] = {
    "flat": {"truth": False, "path": lambda i: 0.0},
    "rising_slow": {"truth": False, "path": lambda i: 0.03 * i},
    "falling": {"truth": False, "path": lambda i: -0.08 * i},
    "plateau": {"truth": False, "path": lambda i: 0.10 * min(i, 2)},
    "rising_fast": {"truth": True, "path": lambda i: 0.08 * i},
    "step_change": {"truth": True, "path": lambda i: 0.0 if i < 4 else 0.6},
}

_N_MONTHS = 6
_BASE = 4.2  # K-like level, safely below the 5.5 flag threshold
_NOISE_SD = 0.05
_REPS_TRUTH_TRUE = 100
_REPS_FLAT = 200  # extra reps for a tighter FP estimate


def _synthetic_series(scenario: str, rng: np.random.Generator) -> list[float]:
    path = _SCENARIOS[scenario]["path"]
    return [
        float(_BASE + path(i) + rng.normal(0.0, _NOISE_SD)) for i in range(_N_MONTHS)
    ]


def _first_detection_month(
    estimator, cfg: dict, series: list[float]
) -> int | None:
    """Number of months of history at which the flag first fires (3..n)."""
    for t in range(trends._MIN_SERIES_LEN, len(series) + 1):
        prefix = series[:t]
        if _would_flag(prefix, estimator(prefix), cfg):
            return t
    return None


def compare_trends(patients: list[dict]) -> dict:
    cfg = trends._THRESHOLDS["K"]  # synthetic scenarios use K-like levels

    # Synthetic scenarios
    # stable per-scenario RNG seeds (never hash(): string hashing is
    # randomised per process)
    scenario_seeds = {
        scenario: SEED + 997 * i for i, scenario in enumerate(_SCENARIOS)
    }
    per_method: dict[str, dict] = {}
    for name, estimator in ESTIMATORS.items():
        stats: dict[str, dict] = {}
        for scenario, spec in _SCENARIOS.items():
            reps = _REPS_FLAT if scenario == "flat" else _REPS_TRUTH_TRUE
            rng = np.random.default_rng(scenario_seeds[scenario])
            end_flagged = 0
            ever_flagged = 0
            leads: list[int] = []
            for _ in range(reps):
                series = _synthetic_series(scenario, rng)
                if _would_flag(series, estimator(series), cfg):
                    end_flagged += 1
                t = _first_detection_month(estimator, cfg, series)
                if t is not None:
                    ever_flagged += 1
                    leads.append(_N_MONTHS - t)
            stats[scenario] = {
                "truth": spec["truth"],
                "end_flag_rate": round(end_flagged / reps, 4),
                "ever_flag_rate": round(ever_flagged / reps, 4),
                # lead = months before the end of the window that the flag
                # first fired (0 = only fires once the full window is seen)
                "mean_lead_months": (
                    round(float(np.mean(leads)), 2) if leads else None
                ),
            }
        tp = [
            stats[s]["end_flag_rate"]
            for s, spec in _SCENARIOS.items()
            if spec["truth"]
        ]
        fp = [
            stats[s]["end_flag_rate"]
            for s, spec in _SCENARIOS.items()
            if not spec["truth"]
        ]
        leads = [
            stats[s]["mean_lead_months"]
            for s, spec in _SCENARIOS.items()
            if spec["truth"] and stats[s]["mean_lead_months"] is not None
        ]
        per_method[name] = {
            "scenarios": stats,
            "detection_rate_true_positive": round(float(np.mean(tp)), 4),
            "false_positive_rate_overall": round(float(np.mean(fp)), 4),
            "false_positive_rate_flat": stats["flat"]["end_flag_rate"],
            "false_positive_rate_plateau": stats["plateau"]["end_flag_rate"],
            "mean_lead_months_true_positive": (
                round(float(np.mean(leads)), 2) if leads else None
            ),
        }

    # Fixture patient series
    real: dict[str, dict] = {}
    slope_deltas: dict[str, list[float]] = {name: [] for name in ESTIMATORS}
    flag_sets: dict[str, set] = {}
    n_series = 0
    for p in patients:
        for analyte, acfg in trends._THRESHOLDS.items():
            series = trends._oldest_first(p, acfg["field"], acfg["serum"])
            if len(series) < trends._MIN_SERIES_LEN:
                continue
            n_series += 1
            ref = trends._theil_sen_slope(series)
            for name, estimator in ESTIMATORS.items():
                slope = estimator(series)
                slope_deltas[name].append(abs(slope - ref))
                if _would_flag(series, slope, acfg):
                    flag_sets.setdefault(name, set()).add((p["patient_id"], analyte))

    ts_flags = flag_sets.get("theil-sen", set())
    module_flags = {(f["patient_id"], f["analyte"]) for f in trends.detect_trends(patients)}
    for name in ESTIMATORS:
        flags = flag_sets.get(name, set())
        jaccard = (
            len(flags & ts_flags) / len(flags | ts_flags)
            if flags or ts_flags
            else 1.0
        )
        real[name] = {
            "n_flags": len(flags),
            "jaccard_vs_theil_sen": round(jaccard, 4),
            "mean_abs_slope_delta_vs_theil_sen": round(
                float(np.mean(slope_deltas[name])), 4
            ),
        }

    results: dict[str, Any] = {
        "n_months": _N_MONTHS,
        "noise_sd": _NOISE_SD,
        "synthetic": per_method,
        "real_patients": {
            "n_series": n_series,
            "per_method": real,
            "matches_trends_module": ts_flags == module_flags,
            "trends_module_n_flags": len(module_flags),
        },
    }
    results["recommendation_method"], results["recommendation"] = _trends_verdict(results)
    return results


def _trends_verdict(results: dict) -> tuple[str, str]:
    def score(name: str) -> tuple[float, float]:
        s = results["synthetic"][name]
        # reward true-positive detection and lead time, penalise false alarms
        return (
            s["detection_rate_true_positive"] - s["false_positive_rate_overall"],
            s["mean_lead_months_true_positive"] or 0.0,
        )

    best = max(ESTIMATORS, key=lambda n: (score(n)[0], score(n)[1], n))
    s = results["synthetic"][best]
    ts = results["synthetic"]["theil-sen"]
    text = (
        f"{best} gives the best detection/robustness trade-off on the "
        f"synthetic ground truth "
        f"(TP detection {s['detection_rate_true_positive']:.0%}, "
        f"flat FP {s['false_positive_rate_flat']:.0%}, "
        f"plateau FP {s['false_positive_rate_plateau']:.0%}, "
        f"mean lead {s['mean_lead_months_true_positive']} months). "
    )
    if best == "theil-sen":
        text += (
            "The current Theil-Sen estimator is also the most robust to "
            "single-month measurement spikes, so no change is needed."
        )
    elif best == "ewma":
        text += (
            "The EWMA-weighted slope adapts fastest when a rise plateaus "
            f"(Theil-Sen plateau FP {ts['false_positive_rate_plateau']:.0%} "
            "vs EWMA's lower rate) because it weights recent months, at some "
            "sensitivity to single-month spikes — a hybrid (flag on "
            "Theil-Sen, de-escalate on EWMA) is worth considering."
        )
    else:
        text += (
            "Plain OLS is competitive here because the synthetic noise is "
            "Gaussian and spike-free, but it is the least robust to a single "
            "bad lab month in real data; Theil-Sen remains the safer "
            "production default."
        )
    real = results["real_patients"]["per_method"]
    if real[best]["n_flags"] != real["theil-sen"]["n_flags"]:
        text += (
            f" On the real cohort it flags {real[best]['n_flags']} series vs "
            f"Theil-Sen's {real['theil-sen']['n_flags']}."
        )
    return best, text


# Substitution comparison

# Renal weights over substitutions.CORE_NUTRIENTS order:
# (energy_kcal, protein_g, sodium_mg, potassium_mg, phosphorus_mg, carbs_g)
RENAL_WEIGHTS: tuple[float, ...] = (1.0, 1.0, 2.0, 2.0, 2.0, 1.0)


def _weighted_distance(dish_a: dict, dish_b: dict) -> float:
    """Euclidean distance with Na/K/P weighted heavier (renal relevance)."""
    va = substitutions._normalised_vector(dish_a)
    vb = substitutions._normalised_vector(dish_b)
    return float(
        sum(w * (a - b) ** 2 for w, a, b in zip(RENAL_WEIGHTS, va, vb)) ** 0.5
    )


def _historical_v2_scores(query: dict, candidates: list[dict]) -> dict[str, float]:
    """Score the study's historical unweighted composite (plain Euclidean term).

    Production v2 ranks by renal-weighted distance. This historical study
    alternative keeps the plain Euclidean nutrient term so the study compares
    distinct nutrient-only, renal-weighted, and composite scorers rather than
    duplicating production under two labels. The persisted ``v2_composite``
    study key and column keep their original spelling for reproducibility.
    """
    nds = [(c, substitutions.nutrient_distance(query, c)) for c in candidates]
    best = min(nd for _, nd in nds)
    scores: dict[str, float] = {}
    for cand, nd in nds:
        adj = nd
        category_match = cand["category"] == query["category"]
        adj -= substitutions._CATEGORY_BONUS if category_match else substitutions._CATEGORY_BONUS / 2
        if query.get("cuisine") and query["cuisine"] == cand.get("cuisine"):
            adj -= substitutions._CUISINE_BONUS
        if nd <= best + substitutions._NEAR_TOLERANCE:
            adj += substitutions._MINERAL_LOAD_WEIGHT * substitutions._mineral_load(cand)
        adj -= substitutions._verification_bonus(cand)
        scores[cand["dish_id"]] = adj
    return scores


def _rank_by(query: dict, candidates: list[dict], metric: str) -> list[str]:
    if metric == "v1_euclidean":
        key = lambda c: (substitutions.nutrient_distance(query, c), c["dish_id"])
    elif metric == "weighted_renal":
        key = lambda c: (_weighted_distance(query, c), c["dish_id"])
    elif metric == "v2_composite":
        scores = _historical_v2_scores(query, candidates)
        key = lambda c: (scores[c["dish_id"]], c["dish_id"])
    else:  # pragma: no cover
        raise ValueError(metric)
    return [c["dish_id"] for c in sorted(candidates, key=key)]


_METRICS = ("v1_euclidean", "weighted_renal", "v2_composite")


def _example_queries(dishes: list[dict]) -> list[dict]:
    """Three representative, deterministically-selected query dishes."""
    hawker = max(
        (d for d in dishes if d["category"] == "hawker"), key=lambda d: d["sodium_mg"]
    )
    drink = max(
        (d for d in dishes if d["category"] == "drink"), key=lambda d: d["sugar_g"]
    )
    zi_char = max(
        (d for d in dishes if d["category"] == "zi_char"),
        key=lambda d: d["phosphorus_mg"],
    )
    return [hawker, drink, zi_char]


def compare_substitutions(dishes: list[dict]) -> dict:
    by_id = {d["dish_id"]: d for d in dishes}
    queries = [d for d in dishes if len(substitutions._candidates(d, dishes)) >= 2]

    rankings: dict[str, dict[str, list[str]]] = {m: {} for m in _METRICS}
    for dish in queries:
        candidates = substitutions._candidates(dish, dishes)
        for metric in _METRICS:
            rankings[metric][dish["dish_id"]] = _rank_by(dish, candidates, metric)

    tau_pairs: dict[str, list[float]] = {}
    for a, b in itertools.combinations(_METRICS, 2):
        taus = []
        for dish in queries:
            # align the two score vectors over the same candidate order
            cand_ids = rankings[a][dish["dish_id"]]
            id_to_score_a = {
                cid: i for i, cid in enumerate(rankings[a][dish["dish_id"]])
            }
            id_to_score_b = {
                cid: i for i, cid in enumerate(rankings[b][dish["dish_id"]])
            }
            xa = [id_to_score_a[cid] for cid in cand_ids]
            xb = [id_to_score_b[cid] for cid in cand_ids]
            taus.append(kendalltau(xa, xb).statistic)
        tau_pairs[f"{a} vs {b}"] = [
            round(float(np.mean(taus)), 4),
            round(float(np.min(taus)), 4),
            round(float(np.max(taus)), 4),
        ]

    # qualitative examples: top-3 under each metric
    examples = []
    for dish in _example_queries(dishes):
        candidates = substitutions._candidates(dish, dishes)
        row: dict[str, str | list[str]] = {"dish": f"{dish['name']} ({dish['category']})"}
        for metric in _METRICS:
            top3 = [
                by_id[cid]["name"] for cid in rankings[metric][dish["dish_id"]][:3]
            ]
            row[metric] = top3
        examples.append(row)

    results: dict[str, Any] = {
        "n_queries": len(queries),
        "renal_weights": dict(zip(substitutions.CORE_NUTRIENTS, RENAL_WEIGHTS)),
        "kendall_tau": tau_pairs,
        "examples": examples,
    }
    results["recommendation"], results["recommendation_metric"] = _substitutions_verdict(
        results
    )
    return results


def _substitutions_verdict(results: dict) -> tuple[str, str]:
    tau = results["kendall_tau"]
    v1_w = tau["v1_euclidean vs weighted_renal"][0]
    divergent_pair = min(tau.items(), key=lambda kv: kv[1][0])
    text = (
        f"Measured rank agreement: mean Kendall τ ranges from "
        f"{min(v[0] for v in tau.values()):.2f} to "
        f"{max(v[0] for v in tau.values()):.2f} across pairs. "
        f"Plain v1 and renal-weighted distance have τ {v1_w:.2f}. The pair that "
        f"diverges most is {divergent_pair[0]} (τ {divergent_pair[1][0]:.2f}), "
        "as illustrated by the top-three examples. "
        "Historical recommendation: retain the composite's category/cuisine "
        "bonuses and lower normalized mineral-load prior, but use a "
        "renal-weighted nutrient term. Rank agreement does not establish "
        "patient safety or clinical benefit. Current production v2 already "
        "uses that renal-weighted term; the serialized v2_composite study "
        "key still denotes the historical unweighted composite."
    )
    return text, "v2_composite"


def load_patients() -> list[dict]:
    with open(PATIENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_comparison() -> dict:
    patients = load_patients()
    dishes = substitutions.load_dishes()
    results = {
        "clustering": compare_clustering(patients),
        "trends": compare_trends(patients),
        "substitutions": compare_substitutions(dishes),
    }
    results["verdicts"] = {
        "clustering": results["clustering"]["recommendation"],
        "trends": results["trends"]["recommendation"],
        "substitutions": results["substitutions"]["recommendation"],
    }
    return results


def build_markdown(r: dict) -> str:
    out: list[str] = []
    out.append("# Mining method-comparison study")
    out.append("")
    out.append(
        "Generated by `backend/mining/comparison.py` (deterministic; fixed "
        "seeds) — do not edit by hand. Re-runs over `data/patients.json` "
        f"({r['clustering']['n_patients']} patients) and `data/dishes.json`."
    )
    out.append("")

    # Clustering
    c = r["clustering"]
    out.append("## 1. Clustering: k-means vs HDBSCAN vs GMM")
    out.append("")
    out.append(
        f"Same standardised features for all methods ({', '.join(c['features'])}); "
        "grid: k-means k∈[2,6]; GMM k∈[2,6] × {diag, full} covariance; HDBSCAN "
        "min_cluster_size ∈ {3,4,5,6}. Best config per method selected by "
        "silhouette (HDBSCAN: silhouette over non-noise points, ≤50% noise)."
    )
    out.append("")
    rows = []
    for name in ("k-means", "gmm", "hdbscan"):
        m = c["methods"][name]
        rows.append(
            [
                name,
                ", ".join(f"{k}={v}" for k, v in m["chosen_config"].items()),
                str(m["n_clusters"]),
                _f(m["silhouette"]),
                _f(m["davies_bouldin"]),
                _f(m["calinski_harabasz"]),
                str(m["noise_points"]),
            ]
        )
    out.append(
        _table(
            ["method", "chosen config", "clusters", "silhouette ↑", "Davies-Bouldin ↓",
             "Calinski-Harabasz ↑", "noise pts"],
            rows,
        )
    )
    out.append("")
    out.append(
        "HDBSCAN metrics are computed on non-noise points only (standard "
        "practice); its noise points are reported separately."
    )
    out.append("")
    stab_rows = []
    for name in ("k-means", "gmm", "hdbscan"):
        m = c["methods"][name]
        stab_rows.append(
            [
                name,
                _f(m["seed_stability_ari"]),
                _f(m["bootstrap_stability_ari"]),
            ]
        )
    out.append(
        _table(
            ["method", "seed stability (mean pairwise ARI over 5 seeds)",
             "bootstrap stability (ARI, 15/20 subsamples × 10)"],
            stab_rows,
        )
    )
    out.append("")
    out.append(
        "*Notes:* HDBSCAN is deterministic by construction, so its seed "
        "stability is trivially 1.0 — the bootstrap-subsample ARI is the "
        "honest stability figure for it. GMM full-covariance BIC keeps "
        "decreasing with k (over-parameterisation at n=20); the "
        "diagonal-covariance BIC minimum is the only usable k-selection "
        "signal it offers."
    )
    out.append("")
    out.append("**Cluster-count behaviour**")
    out.append("")
    bic_rows = [
        [str(k), _f(c["gmm_bic_by_k"]["diag"][k], 1), _f(c["gmm_bic_by_k"]["full"][k], 1),
         _f(c["kmeans_silhouette_by_k"][k])]
        for k in sorted(c["kmeans_silhouette_by_k"])
    ]
    out.append(
        _table(
            ["k", "GMM BIC (diag) ↓", "GMM BIC (full) ↓", "k-means silhouette"],
            bic_rows,
        )
    )
    out.append("")
    hd_rows = [
        [str(mcs), str(v["noise_points"]), str(v["n_clusters"])]
        for mcs, v in sorted(c["hdbscan_noise_by_min_cluster_size"].items())
    ]
    out.append(
        _table(["HDBSCAN min_cluster_size", "noise points (of 20)", "clusters found"], hd_rows)
    )
    out.append("")
    win_rows = [
        [metric, winner] for metric, winner in c["metric_winners"].items()
    ]
    out.append(_table(["metric", "winner"], win_rows))
    out.append("")
    out.append(f"**Verdict — {c['recommendation_method']}.** {c['recommendation']}")
    out.append("")

    # Trends
    t = r["trends"]
    out.append("## 2. Trend detection: Theil-Sen vs OLS vs EWMA")
    out.append("")
    out.append(
        f"Synthetic 6-month K-like series (base {_BASE}, noise σ={t['noise_sd']}), "
        "200 flat replications and 100 per other scenario; the trends.py flag rule "
        "(slope > 0.05/month or 3-month projection crossing) is applied "
        "identically to every estimator. EWMA = exponentially weighted "
        "least-squares slope (half-life 2 months)."
    )
    out.append("")
    scen_rows = []
    for scenario, spec in _SCENARIOS.items():
        row = [scenario, "flag" if spec["truth"] else "no flag"]
        for name in ESTIMATORS:
            s = t["synthetic"][name]["scenarios"][scenario]
            if spec["truth"]:
                lead = (
                    f"lead {s['mean_lead_months']} mo"
                    if s["mean_lead_months"] is not None
                    else "—"
                )
                cell = f"end {s['end_flag_rate']:.0%} · {lead}"
            else:
                cell = (
                    f"end {s['end_flag_rate']:.0%} · ever {s['ever_flag_rate']:.0%}"
                )
            row.append(cell)
        scen_rows.append(row)
    out.append(_table(["scenario", "truth", "theil-sen", "ols", "ewma"], scen_rows))
    out.append("")
    summ_rows = []
    for name in ESTIMATORS:
        s = t["synthetic"][name]
        summ_rows.append(
            [
                name,
                f"{s['detection_rate_true_positive']:.0%}",
                f"{s['false_positive_rate_flat']:.0%}",
                f"{s['false_positive_rate_plateau']:.0%}",
                f"{s['false_positive_rate_overall']:.0%}",
                _f(s["mean_lead_months_true_positive"], 2),
            ]
        )
    out.append(
        _table(
            ["method", "TP detection (end) ↑", "FP flat (end) ↓",
             "FP plateau (end) ↓", "FP all no-flag scenarios ↓", "mean lead (mo) ↑"],
            summ_rows,
        )
    )
    out.append("")
    out.append(
        "*Reading the table:* for no-flag scenarios, `end` is the "
        "false-positive rate on the full 6-month series and `ever` adds "
        "transient mid-window alarms (the union over all prefixes). "
        "`plateau` is the adaptivity probe — a series that rose for 3 months "
        "then stabilised should **not** still be flagged at month 6; "
        "history-dominated estimators keep flagging it. For flag scenarios, "
        "`lead` is how many months before the end of the window the flag "
        "first fired; `step_change` is undetectable before the jump itself, "
        "so its lead is naturally small."
    )
    out.append("")
    rp = t["real_patients"]
    real_rows = [
        [
            name,
            str(rp["per_method"][name]["n_flags"]),
            _f(rp["per_method"][name]["jaccard_vs_theil_sen"]),
            _f(rp["per_method"][name]["mean_abs_slope_delta_vs_theil_sen"]),
        ]
        for name in ESTIMATORS
    ]
    out.append(
        _table(
            ["method", f"flags on real cohort ({rp['n_series']} series)",
             "Jaccard vs theil-sen", "mean |Δslope| vs theil-sen"],
            real_rows,
        )
    )
    out.append("")
    out.append(
        f"The theil-sen column reproduces `trends.detect_trends` exactly: "
        f"**{rp['matches_trends_module']}** "
        f"(module reports {rp['trends_module_n_flags']} flags)."
    )
    out.append("")
    out.append(f"**Verdict — {t['recommendation_method']}.** {t['recommendation']}")
    out.append("")

    # Substitutions
    s = r["substitutions"]
    out.append("## 3. Substitution metrics: v1 euclidean vs renal-weighted vs historical composite")
    out.append("")
    out.append(
        f"Ranked candidate sets per query dish ({s['n_queries']} queries with "
        "≥2 compatible candidates). Renal weights (Na/K/P ×2): "
        + ", ".join(f"{k}={v:g}" for k, v in s["renal_weights"].items())
        + "."
    )
    out.append(
        "The `v2_composite` study key denotes the historical unweighted composite, "
        "not the current renal-weighted production v2."
    )
    out.append("")
    tau_rows = [
        [pair, _f(vals[0]), _f(vals[1]), _f(vals[2])]
        for pair, vals in s["kendall_tau"].items()
    ]
    out.append(
        _table(["metric pair", "mean Kendall τ", "min τ", "max τ"], tau_rows)
    )
    out.append("")
    ex_rows = [
        [
            e["dish"],
            "; ".join(e["v1_euclidean"]),
            "; ".join(e["weighted_renal"]),
            "; ".join(e["v2_composite"]),
        ]
        for e in s["examples"]
    ]
    out.append(
        _table(
            ["example dish", "v1 euclidean top-3", "renal-weighted top-3", "historical unweighted composite top-3"],
            ex_rows,
        )
    )
    out.append("")
    out.append(f"**Verdict — {s['recommendation_metric']}.** {s['recommendation']}")
    out.append("")

    out.append("## Current production")
    out.append("")
    out.append(
        "Production methods differ from the historical study alternatives. "
        "Regression tests live in "
        "`backend/mining/test_mining.py`:"
    )
    out.append("")
    out.append(
        "* **Trend detection — hybrid Theil-Sen flag / EWMA de-escalation** "
        "(`trends.py`). Theil-Sen raises trend flags; dated observations also "
        "flag an urgent latest value. EWMA uses a two-month half-life and can "
        "downgrade severity to `review` when it no longer satisfies the trend "
        "rule. An urgent latest dated observation remains urgent. "
        "Test: `TestTrends::test_plateau_downgraded_by_ewma`."
    )
    out.append(
        "* **Substitutions — renal-weighted nutrient term in the v2 "
        "composite** (`substitutions.py`). Production v2 ranks by "
        "`renal_nutrient_distance` (Na/K/P ×2) instead of the plain "
        "Euclidean term. Category compatibility and cuisine bonuses remain, "
        "with a lower normalized mineral-load prior for near-distance candidates "
        "and hpb_id/verified score bonuses. Test: "
        "`TestSubstitutions::test_v2_uses_renal_weighted_distance`."
    )
    out.append("")
    out.append(
        "*Note:* the `v2_composite` column in section 3 reflects the "
        "composite as studied (plain euclidean nutrient term), so the "
        "comparison stays reproducible as originally run; production v2 "
        "differs by the adopted renal weighting."
    )
    out.append("")

    out.append("## Summary")
    out.append("")
    out.append("| family | recommendation |")
    out.append("|---|---|")
    out.append(f"| clustering | **{c['recommendation_method']}** |")
    out.append(f"| trend detection | **{t['recommendation_method']}** |")
    out.append(f"| substitutions | **{s['recommendation_metric']}** |")
    out.append("")
    return "\n".join(out) + "\n"


def main(output_path: Path | None = None) -> int:
    """Run the study and write Markdown to the supplied path or default report."""
    results = run_comparison()
    markdown = build_markdown(results)
    destination = COMPARISON_MD_PATH if output_path is None else output_path
    destination.write_text(markdown, encoding="utf-8")

    print("Method-comparison study complete.")
    print(f"Report written to {destination}")
    print()
    print("Headline verdicts")
    print(f"  clustering    : {results['clustering']['recommendation_method']}")
    print(f"  trends        : {results['trends']['recommendation_method']}")
    print(f"  substitutions : {results['substitutions']['recommendation_metric']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
