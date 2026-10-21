"""Trend explanations identify the trigger without changing alert policy."""

import pytest

from backend.mining.trends import detect_trends


def _patient(values):
    return {"patient_id": "p-reason", "observations": [
        {"observation_id": str(i), "observed_at": f"2026-{i + 1:02d}-01",
         "metric": "serum_K_meq_L", "value": value}
        for i, value in enumerate(values)
    ]}


@pytest.mark.parametrize("values", [[5.8], [6.0, 5.9, 5.8], [5.8, 5.8, 5.8]])
def test_urgent_latest_without_rise_is_explained_as_alert(values):
    flag, = detect_trends([_patient(values)])
    assert flag["severity"] == "urgent"
    assert "clinical alert level" in flag["reason"]
    assert "rising +" not in flag["reason"]
    assert "no rising trend measured" in flag["reason"]


def test_measured_rise_reason():
    flag, = detect_trends([_patient([4.0, 4.2, 4.4])])
    assert "rising" in flag["reason"]
    assert flag["slope_per_month"] > 0.05


def test_projected_crossing_without_slope_trigger_reason():
    flag, = detect_trends([_patient([5.40, 5.44, 5.48])])
    assert "crosses" in flag["reason"]
    assert 0 < flag["slope_per_month"] < 0.05
    assert flag["projected_3mo"] > 5.5
