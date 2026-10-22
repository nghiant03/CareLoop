"""Provider-free discovery fixtures; no network or live databases."""

import copy
from types import SimpleNamespace

import pytest

from backend.knowledge import discovery

TEXT = "General nutrition guidance: adults should aim for 28 g of fibre daily.\fLimit sodium to 1800 mg daily in this study population."
FIBRE = {"section": "Nutrition", "nutrient": "fiber_g", "kind": "TARGET", "value": 28,
         "basis": "g_per_day", "quote": "adults should aim for 28 g of fibre daily.",
         "source_population": "Adults", "caveats": ["Check the full guideline for exceptions"]}
SODIUM = {"section": "Diet", "nutrient": "sodium_mg", "kind": "MAX", "value": 1800,
          "basis": "mg_per_day", "quote": "Limit sodium to 1800 mg daily in this study population.",
          "source_population": "Source-defined population", "source_unit": "mg/day",
          "source_value": 1800, "source_operator": "limit", "evidence_grade": "source grade"}


class FakeDiscoveryClient:
    model = "test-model"

    def __init__(self, candidates=None):
        self.candidates = copy.deepcopy(candidates if candidates is not None else [FIBRE, SODIUM])
        self.calls = []

    def extract_candidates(self, *, instructions, source_text):
        self.calls.append({"instructions": instructions, "source_text": source_text})
        return {"candidates": copy.deepcopy(self.candidates)}


@pytest.fixture
def baseline():
    return {"dsl_version": "1.0", "rules": [
        {"rule_id": "FIBRE-BASELINE", "priority": 60, "conditions": [],
         "actions": [{"type": "set_constraint", "nutrient": "fiber_g", "kind": "min", "value": 25}]},
    ]}


@pytest.fixture
def llm_client():
    return FakeDiscoveryClient()


@pytest.fixture
def source_file(tmp_path, monkeypatch):
    path = tmp_path / "another-guideline.pdf"
    path.write_bytes(b"%PDF-test-source")
    monkeypatch.setattr(discovery.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=TEXT.encode()))
    return path
