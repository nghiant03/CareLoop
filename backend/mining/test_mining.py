"""Tests for backend.mining: clustering, substitutions, trends.

Run from the repo root:  .venv/bin/python -m pytest backend/mining -q
"""

import json
from pathlib import Path

import pytest

from backend.mining import clustering, substitutions, trends

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def patients() -> list[dict]:
    with open(DATA_DIR / "patients.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dishes() -> list[dict]:
    return substitutions.load_dishes()


# ---------------------------------------------------------------------------
# clustering
# ---------------------------------------------------------------------------


class TestClustering:
    def test_deterministic(self, patients):
        first = clustering.cluster_patients(patients)
        second = clustering.cluster_patients(patients)
        assert first == second

    def test_structure_and_coverage(self, patients):
        result = clustering.cluster_patients(patients)
        assert 2 <= result["k"] <= 6
        assert len(result["labels"]) == len(patients) == 20
        assert set(result["labels"]) == set(result["profiles"])
        assert -1.0 <= result["silhouette"] <= 1.0
        # every patient accounted for exactly once across profiles
        assert sum(prof["size"] for prof in result["profiles"].values()) == 20
        for prof in result["profiles"].values():
            assert set(prof["means"]) == set(result["feature_names"])
            assert prof["dominant_diagnoses"], "each cluster should have diagnoses"

    def test_k_range_respected(self, patients):
        result = clustering.cluster_patients(patients, k_range=(4, 4))
        assert result["k"] == 4

    def test_custom_k_range(self, patients):
        result = clustering.cluster_patients(patients, k_range=(2, 3))
        assert 2 <= result["k"] <= 3


# ---------------------------------------------------------------------------
# substitutions
# ---------------------------------------------------------------------------


class TestSubstitutions:
    def test_nutrient_distance_identical_and_extremes(self, dishes):
        a = dishes[0]
        assert substitutions.nutrient_distance(a, a) == 0.0
        # distance is symmetric
        b = dishes[50]
        d_ab = substitutions.nutrient_distance(a, b)
        assert d_ab == pytest.approx(substitutions.nutrient_distance(b, a))
        assert 0.0 <= d_ab <= 6 ** 0.5 + 1e-9

    def test_v2_uses_renal_weighted_distance(self, dishes):
        """The v2 composite's nutrient term is
        the renal-weighted distance (Na/K/P ×2), not the plain euclidean."""
        dish = next(d for d in dishes if d["dish_id"] == "SG0001")
        results = substitutions.suggest_substitutions("SG0001", k=5, version=2, dishes=dishes)
        assert results
        for r in results:
            cand = next(d for d in dishes if d["dish_id"] == r["dish_id"])
            assert r["nutrient_distance"] == pytest.approx(
                substitutions.renal_nutrient_distance(dish, cand), abs=1e-4
            )

    def test_renal_weighting_changes_ranking(self, dishes):
        """The renal weighting must actually matter: for some query dish the
        plain and renal-weighted distances order candidates differently."""
        differing = 0
        by_id = {d["dish_id"]: d for d in dishes}
        for dish in dishes:
            cands = substitutions._candidates(dish, dishes)
            if len(cands) < 2:
                continue
            plain = sorted(c["dish_id"] for c in cands)
            renal = sorted(c["dish_id"] for c in cands)
            plain.sort(key=lambda cid: substitutions.nutrient_distance(dish, by_id[cid]))
            renal.sort(key=lambda cid: substitutions.renal_nutrient_distance(dish, by_id[cid]))
            if plain != renal:
                differing += 1
        assert differing > 0, "renal weighting never changes any ranking"

    def test_v1_excludes_query_and_ranks_by_distance(self, dishes):
        results = substitutions.suggest_substitutions("SG0001", k=5, version=1, dishes=dishes)
        assert len(results) == 5
        assert all(r["dish_id"] != "SG0001" for r in results)
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
        for r in results:
            assert r["distance"] == pytest.approx(r["nutrient_distance"])

    def test_v2_result_shape_and_ranking(self, dishes):
        results = substitutions.suggest_substitutions("SG0001", k=3, version=2, dishes=dishes)
        assert len(results) == 3
        assert [r["distance"] for r in results] == sorted(r["distance"] for r in results)
        for r in results:
            assert set(r) == {
                "dish_id", "name", "distance", "nutrient_distance",
                "category_match", "reason", "ranking_score",
            }
            assert r["ranking_score"] == r["distance"]
            assert isinstance(r["reason"], str) and r["reason"]

    def test_category_logic_drink_never_soup(self, dishes):
        drink = next(d for d in dishes if d["category"] == "drink")
        results = substitutions.suggest_substitutions(drink["dish_id"], k=5, version=2, dishes=dishes)
        assert results, "drink should have drink/dessert candidates"
        cats = {d["category"] for d in dishes if d["dish_id"] in {r["dish_id"] for r in results}}
        assert cats <= {"drink", "dessert"}
        assert "soup" not in cats

    def test_dessert_candidates(self, dishes):
        dessert = next(d for d in dishes if d["category"] == "dessert")
        results = substitutions.suggest_substitutions(dessert["dish_id"], k=3, version=2, dishes=dishes)
        cats = {d["category"] for d in dishes if d["dish_id"] in {r["dish_id"] for r in results}}
        assert cats <= {"dessert", "drink"}

    def test_meal_suggestions_stay_in_meal_categories(self, dishes):
        hawker = next(d for d in dishes if d["category"] == "hawker")
        results = substitutions.suggest_substitutions(hawker["dish_id"], k=5, version=2, dishes=dishes)
        cats = {d["category"] for d in dishes if d["dish_id"] in {r["dish_id"] for r in results}}
        assert cats <= {"hawker", "cai_png"}

    def test_unknown_dish_raises(self, dishes):
        with pytest.raises(KeyError):
            substitutions.suggest_substitutions("NOPE-404", dishes=dishes)

    def test_deterministic(self, dishes):
        a = substitutions.suggest_substitutions("SG0001", k=3, version=2, dishes=dishes)
        b = substitutions.suggest_substitutions("SG0001", k=3, version=2, dishes=dishes)
        assert a == b

    def test_healthier_prior_prefers_lower_minerals(self, dishes):
        """Among near-distance candidates, v2 should not systematically pick
        the mineral-heaviest option."""
        salty = max(dishes, key=lambda d: d["sodium_mg"])
        results = substitutions.suggest_substitutions(salty["dish_id"], k=5, version=2, dishes=dishes)
        picked = {r["dish_id"] for r in results}
        query_minerals = salty["sodium_mg"] + salty["potassium_mg"] + salty["phosphorus_mg"]
        better = [
            d["dish_id"]
            for d in dishes
            if d["dish_id"] in picked
            and (d["sodium_mg"] + d["potassium_mg"] + d["phosphorus_mg"]) < query_minerals
        ]
        assert better, "at least one suggestion should be lighter in minerals"

    def test_k_respected_with_small_pool(self, dishes):
        dessert = next(d for d in dishes if d["category"] == "dessert")
        results = substitutions.suggest_substitutions(dessert["dish_id"], k=10, version=2, dishes=dishes)
        # The compatible category pool bounds the number returned, even for large k.
        assert 0 < len(results) <= 10


# ---------------------------------------------------------------------------
# trends
# ---------------------------------------------------------------------------


def _synthetic_patient(pid: str, values_newest_first: list[float], analyte: str = "K") -> dict:
    field = "labs_K_monthly" if analyte == "K" else "labs_PO4_monthly"
    return {
        "patient_id": pid,
        "months_offset_ago": list(range(len(values_newest_first))),
        field: values_newest_first,
        "serum_K_meq_L": values_newest_first[0] if analyte == "K" else None,
        "serum_PO4_mg_dL": values_newest_first[0] if analyte == "PO4" else None,
    }


class TestTrends:
    def test_flags_known_rising_patient(self, patients):
        """P0016 has a clearly rising PO4 series in the synthetic data."""
        flags = trends.detect_trends(patients)
        assert flags, "dataset contains rising patients; none flagged"
        p0016 = [f for f in flags if f["patient_id"] == "P0016" and f["analyte"] == "PO4"]
        assert p0016, "P0016 PO4 should be flagged"
        assert p0016[0]["slope_per_month"] > 0.05
        assert p0016[0]["severity"] in {"review", "urgent"}
        # a genuinely rising series is confirmed by the EWMA check
        assert p0016[0]["ewma_slope_per_month"] > 0.05

    def test_flag_shape_and_values_are_oldest_first(self, patients):
        flags = trends.detect_trends(patients)
        for f in flags:
            assert set(f) >= {
                "patient_id", "analyte", "slope_per_month", "ewma_slope_per_month",
                "values", "projected_3mo", "severity", "reason",
            }
            assert f["analyte"] in {"K", "PO4"}
            assert f["severity"] in {"review", "urgent"}
            # values returned oldest->newest: last element == current serum
            patient = next(p for p in patients if p["patient_id"] == f["patient_id"])
            serum = patient["serum_K_meq_L"] if f["analyte"] == "K" else patient["serum_PO4_mg_dL"]
            assert f["values"][-1] == pytest.approx(serum)

    def test_plateau_downgraded_by_ewma(self):
        """Hybrid de-escalation: a series that rose and
        then flattened is still flagged by the full-window Theil-Sen rule,
        but the recent-regime EWMA slope no longer satisfies the flag rule,
        so severity is downgraded to review with a reason saying why."""
        # oldest-first: 4.6 -> 5.2 over 2 months, then essentially flat.
        # Theil-Sen slope +0.0667 (> 0.05 trigger) and latest 5.05 >= 5.0
        # alert level -> would be "urgent" under the old rule.
        plateau = _synthetic_patient("SYN-PLATEAU", [5.05, 5.1, 5.15, 5.2, 4.9, 4.6])
        flags = trends.detect_trends([plateau])
        assert len(flags) == 1
        f = flags[0]
        assert f["analyte"] == "K"
        assert f["slope_per_month"] == pytest.approx(0.0667, abs=0.005)
        assert f["slope_per_month"] > 0.05, "Theil-Sen must still flag"
        assert f["ewma_slope_per_month"] < 0.05, "EWMA sees no current rise"
        assert f["severity"] == "review"
        assert "EWMA" in f["reason"]

    def test_flagged_by_both_keeps_urgent(self):
        """A series rising fast right up to the present is flagged by both
        Theil-Sen and EWMA and keeps severity 'urgent'."""
        rising = _synthetic_patient("SYN-K", [5.6, 5.5, 5.35, 5.2, 5.1, 5.0])
        flags = trends.detect_trends([rising])
        assert len(flags) == 1
        assert flags[0]["severity"] == "urgent"
        assert flags[0]["ewma_slope_per_month"] > 0.05
        assert "EWMA" not in flags[0]["reason"]

    def test_stable_patient_not_flagged(self, patients):
        flat = _synthetic_patient("SYN-FLAT", [4.0, 4.0, 4.0, 4.0, 4.0, 4.0])
        assert trends.detect_trends([flat]) == []

    def test_synthetic_rising_k_flagged_urgent(self):
        rising = _synthetic_patient("SYN-K", [5.6, 5.5, 5.35, 5.2, 5.1, 5.0])
        flags = trends.detect_trends([rising])
        assert len(flags) == 1
        f = flags[0]
        assert f["analyte"] == "K"
        assert f["slope_per_month"] == pytest.approx(0.125, abs=0.02)
        assert f["values"] == [5.0, 5.1, 5.2, 5.35, 5.5, 5.6]
        assert f["severity"] == "urgent"
        assert f["projected_3mo"] >= 5.5

    def test_synthetic_gentle_rise_is_review(self):
        rising = _synthetic_patient("SYN-K2", [4.45, 4.4, 4.34, 4.28, 4.22, 4.15])
        flags = trends.detect_trends([rising])
        assert len(flags) == 1
        assert flags[0]["severity"] == "review"

    def test_orientation_descending_offsets(self):
        """months_offset_ago descending to 0 means data is already oldest-first."""
        patient = {
            "patient_id": "SYN-OLD",
            "months_offset_ago": [5, 4, 3, 2, 1, 0],
            "labs_K_monthly": [4.0, 4.1, 4.2, 4.3, 4.4, 4.5],
        }
        flags = trends.detect_trends([patient])
        assert len(flags) == 1
        assert flags[0]["values"] == [4.0, 4.1, 4.2, 4.3, 4.4, 4.5]
        assert flags[0]["slope_per_month"] == pytest.approx(0.1, abs=0.01)

    def test_orientation_ascending_offsets_reversed(self):
        """months_offset_ago ascending from 0 (dataset convention) is newest-first."""
        patient = {
            "patient_id": "SYN-NEW",
            "months_offset_ago": [0, 1, 2, 3, 4, 5],
            "labs_K_monthly": [4.0, 4.1, 4.2, 4.3, 4.4, 4.5],
        }
        flags = trends.detect_trends([patient])
        assert flags == [], "this orientation encodes a *falling* trend"

    def test_short_series_ignored(self):
        patient = {"patient_id": "SYN-SHORT", "labs_K_monthly": [5.9, 5.8]}
        assert trends.detect_trends([patient]) == []

    def test_deterministic(self, patients):
        assert trends.detect_trends(patients) == trends.detect_trends(patients)
