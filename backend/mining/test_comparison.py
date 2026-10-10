"""Tests for backend.mining.comparison — the method-comparison study.

A module-scoped fixture exercises main()'s artifact writing and shares a study
result across assertions. Runtime depends on the numerical environment.
"""

import math
from pathlib import Path

import pytest

from backend.mining import comparison

COMPARISON_MD = Path(comparison.__file__).resolve().parent / "COMPARISON.md"


@pytest.fixture(scope="module")
def results():
    assert comparison.main() == 0
    return comparison.run_comparison()


class TestStructure:
    def test_top_level_keys(self, results):
        assert set(results) >= {"clustering", "trends", "substitutions", "verdicts"}
        assert set(results["verdicts"]) == {"clustering", "trends", "substitutions"}
        assert all(isinstance(v, str) and v for v in results["verdicts"].values())

    def test_deterministic(self, results):
        again = comparison.run_comparison()
        assert again == results


class TestClustering:
    def test_methods_and_finite_metrics(self, results):
        c = results["clustering"]
        assert c["n_patients"] == 20
        assert set(c["methods"]) == {"k-means", "gmm", "hdbscan"}
        for name, m in c["methods"].items():
            for key in ("silhouette", "davies_bouldin", "calinski_harabasz"):
                if m[key] is not None:
                    assert math.isfinite(m[key]), (name, key)
            if m["silhouette"] is not None:
                assert -1.0 <= m["silhouette"] <= 1.0
            assert 0 <= m["noise_points"] <= c["n_patients"]
            # stability: ARI lives in [-1, 1]
            for key in ("seed_stability_ari", "bootstrap_stability_ari"):
                assert -1.0 <= m[key] <= 1.0

    def test_cluster_count_behaviour_tables(self, results):
        c = results["clustering"]
        assert set(c["gmm_bic_by_k"]) == {"diag", "full"}
        assert all(math.isfinite(b) for cov in c["gmm_bic_by_k"].values() for b in cov.values())
        assert c["hdbscan_noise_by_min_cluster_size"]
        for info in c["hdbscan_noise_by_min_cluster_size"].values():
            assert 0 <= info["noise_points"] <= 20
            assert info["n_clusters"] >= 0

    def test_verdicts_present_and_groundable(self, results):
        c = results["clustering"]
        assert set(c["metric_winners"]) == {
            "silhouette",
            "davies_bouldin",
            "calinski_harabasz",
            "seed_stability_ari",
            "bootstrap_stability_ari",
        }
        assert all(w in c["methods"] for w in c["metric_winners"].values())
        assert c["recommendation_method"] in c["methods"]
        assert len(c["recommendation"]) > 80
        assert results["verdicts"]["clustering"] == c["recommendation"]


class TestTrends:
    def test_scenario_stats_are_sane(self, results):
        t = results["trends"]
        for name, method in t["synthetic"].items():
            assert name in {"theil-sen", "ols", "ewma"}
            for scenario, s in method["scenarios"].items():
                assert 0.0 <= s["end_flag_rate"] <= 1.0, (name, scenario)
                assert 0.0 <= s["ever_flag_rate"] <= 1.0
                assert s["ever_flag_rate"] >= s["end_flag_rate"]
                if s["mean_lead_months"] is not None:
                    assert 0.0 <= s["mean_lead_months"] <= comparison._N_MONTHS

    def test_true_positives_detected(self, results):
        """Both should-flag scenarios are detected by every estimator."""
        for name, method in results["trends"]["synthetic"].items():
            assert method["detection_rate_true_positive"] >= 0.9, name

    def test_flat_false_positive_rate_low(self, results):
        for name, method in results["trends"]["synthetic"].items():
            assert method["false_positive_rate_flat"] <= 0.2, name

    def test_ewma_adapts_to_plateau_better_than_theil_sen(self, results):
        """The headline differentiator: after a rise stops, the
        EWMA-weighted slope must stop flagging sooner than Theil-Sen."""
        t = results["trends"]["synthetic"]
        assert (
            t["ewma"]["false_positive_rate_plateau"]
            < t["theil-sen"]["false_positive_rate_plateau"]
        )

    def test_real_data_reproduces_trends_module(self, results):
        rp = results["trends"]["real_patients"]
        assert rp["n_series"] == 40  # 20 patients x 2 analytes
        assert rp["matches_trends_module"] is True
        assert rp["per_method"]["theil-sen"]["n_flags"] == rp["trends_module_n_flags"]
        for name, m in rp["per_method"].items():
            assert 0.0 <= m["jaccard_vs_theil_sen"] <= 1.0
            assert m["mean_abs_slope_delta_vs_theil_sen"] >= 0.0


class TestSubstitutions:
    def test_kendall_tau_in_range(self, results):
        s = results["substitutions"]
        assert s["n_queries"] > 0
        assert set(s["renal_weights"]) == set(comparison.substitutions.CORE_NUTRIENTS)
        assert s["renal_weights"]["sodium_mg"] > s["renal_weights"]["energy_kcal"]
        for pair, (mean, lo, hi) in s["kendall_tau"].items():
            assert -1.0 <= lo <= hi <= 1.0, pair
            assert lo <= mean <= hi

    def test_examples_three_dishes_three_metrics(self, results):
        examples = results["substitutions"]["examples"]
        assert len(examples) == 3
        for e in examples:
            assert e["dish"]
            for metric in ("v1_euclidean", "weighted_renal", "v2_composite"):
                assert len(e[metric]) == 3
                assert all(isinstance(n, str) and n for n in e[metric])

    def test_verdict_present(self, results):
        s = results["substitutions"]
        assert s["recommendation_metric"] in {"v1_euclidean", "weighted_renal", "v2_composite"}
        assert len(s["recommendation"]) > 80
        assert results["verdicts"]["substitutions"] == s["recommendation"]


class TestArtifact:
    def test_markdown_written_with_tables_and_verdicts(self, results):
        assert COMPARISON_MD.exists()
        text = COMPARISON_MD.read_text(encoding="utf-8")
        for heading in (
            "# Mining method-comparison study",
            "## 1. Clustering",
            "## 2. Trend detection",
            "## 3. Substitution metrics",
            "## Summary",
        ):
            assert heading in text
        assert text.count("**Verdict") == 3
        # markdown tables present
        assert text.count("|---") >= 6
