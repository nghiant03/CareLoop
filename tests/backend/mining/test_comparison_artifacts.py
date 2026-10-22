import json
from pathlib import Path

import numpy as np

from backend.mining import comparison
from backend.storage_paths import dataset_dir


def test_comparison_output_uses_artifacts_and_preserves_published_report(monkeypatch, tmp_path):
    assert not Path(comparison.__file__).with_name("COMPARISON.md").exists()
    published = dataset_dir() / "benchmarks/COMPARISON.md"
    before = published.read_bytes()
    results = {"clustering":{"recommendation_method":"synthetic"},
               "trends":{"recommendation_method":"synthetic"},
               "substitutions":{"recommendation_metric":"synthetic"},
               "undefined": float("nan"), "numerical":np.float64(1.5)}
    monkeypatch.setattr(comparison, "run_comparison", lambda: results)
    monkeypatch.setattr(comparison, "build_markdown", lambda _: "# Synthetic comparison\n")
    monkeypatch.setattr(comparison, "COMPARISON_MD_PATH", tmp_path / "artifacts/mining/COMPARISON.md")
    assert comparison.main() == 0
    assert (tmp_path / "artifacts/mining/COMPARISON.md").read_text() == "# Synthetic comparison\n"
    stored = json.loads((tmp_path / "artifacts/mining/comparison_results.json").read_text())
    assert stored["undefined"] is None and stored["numerical"] == 1.5
    assert published.read_bytes() == before
    explicit = tmp_path / "explicit/selected.md"
    assert comparison.main(explicit) == 0
    assert explicit.is_file() and explicit.with_name("comparison_results.json").is_file()

