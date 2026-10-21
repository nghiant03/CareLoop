"""External datasets never fall back to source-tree seeds or create files."""

from pathlib import Path

import pytest

from backend.datasets.paths import dataset_dir, dataset_path
from backend.storage_paths import artifact_dir


def test_default_uses_xdg_data_home_without_creating_files(monkeypatch, tmp_path):
    monkeypatch.delenv("CARELOOP_DATASET_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert dataset_dir() == tmp_path / "share/careloop/datasets"
    assert dataset_path("patients.json") == dataset_dir() / "fixtures/patients.json"
    assert not (tmp_path / "share").exists()


def test_configured_root_and_output_are_external(monkeypatch, tmp_path):
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(tmp_path / "external"))
    monkeypatch.delenv("CARELOOP_ARTIFACT_DIR", raising=False)
    assert dataset_path("dishes.json") == tmp_path / "external/fixtures/dishes.json"
    assert artifact_dir("evaluation") == tmp_path / "external/outputs/evaluation"


def test_checkout_dataset_roots_are_rejected(monkeypatch):
    checkout = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(checkout / "datasets"))
    with pytest.raises(ValueError, match="outside"):
        dataset_dir()
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(checkout / "artifacts"))
    with pytest.raises(ValueError, match="outside"):
        artifact_dir("evaluation")


def test_relative_roots_and_unknown_fixtures_are_rejected(monkeypatch):
    monkeypatch.setenv("CARELOOP_DATASET_DIR", "datasets")
    with pytest.raises(ValueError, match="absolute"):
        dataset_dir()
    with pytest.raises(ValueError, match="Unknown"):
        dataset_path("../patients.json")


def test_symlink_into_checkout_is_rejected(monkeypatch, tmp_path):
    link = tmp_path / "external"
    link.symlink_to(Path(__file__).resolve().parents[3], target_is_directory=True)
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(link))
    with pytest.raises(ValueError, match="outside"):
        dataset_dir()
