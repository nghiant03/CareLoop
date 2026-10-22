"""Source/provider failures never trigger a static-pattern fallback."""

import subprocess
from types import SimpleNamespace

import pytest

from backend.knowledge import discovery
from tests.backend.knowledge.conftest import TEXT, FakeDiscoveryClient


def test_extractor_receives_selected_bytes_without_hash_validation(source_file, baseline, llm_client, monkeypatch):
    expected = source_file.read_bytes()

    def extract(command, **kwargs):
        assert command == ["pdftotext", "-layout", "-", "-"]
        assert kwargs["input"] == expected
        assert kwargs["timeout"] == 120
        return SimpleNamespace(stdout=TEXT.encode())

    monkeypatch.setattr(discovery.subprocess, "run", extract)
    assert discovery.discover_rules([source_file], baseline, llm_client)["candidates"]


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.CalledProcessError(1, ["pdftotext"]), subprocess.TimeoutExpired(["pdftotext"], 120)])
def test_pdf_failure_is_explicit(source_file, baseline, llm_client, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(discovery.subprocess, "run", fail)
    with pytest.raises(RuntimeError):
        discovery.discover_rules([source_file], baseline, llm_client)
    assert not llm_client.calls


def test_provider_failure_is_not_a_successful_pattern_report(source_file, baseline, llm_client, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(llm_client, "extract_candidates", fail)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        discovery.discover_rules([source_file], baseline, llm_client)


@pytest.mark.parametrize("response", [None, [], {}, {"candidates": "not a list"}])
def test_malformed_provider_output_fails_closed(baseline, response):
    client = SimpleNamespace(extract_candidates=lambda **kwargs: response)
    with pytest.raises(TypeError, match="candidates"):
        discovery.propose_rules(TEXT, {"path": "guideline.txt"}, baseline, client)


def test_no_valid_candidates_is_not_success(source_file, baseline):
    with pytest.raises(ValueError, match="No valid"):
        discovery.discover_rules([source_file], baseline, FakeDiscoveryClient([]))


def test_non_pdf_empty_and_unsupported_sources_fail(source_file, baseline, llm_client, tmp_path):
    source_file.write_bytes(b"HTML access page")
    with pytest.raises(ValueError, match="not a PDF"):
        discovery.discover_rules([source_file], baseline, llm_client)
    empty = tmp_path / "empty.txt"
    empty.write_text("  ")
    with pytest.raises(ValueError, match="no extractable text"):
        discovery.discover_rules([empty], baseline, llm_client)
    with pytest.raises(ValueError, match="Unsupported"):
        discovery.discover_rules([tmp_path / "source.zip"], baseline, llm_client)


def test_source_metadata_counts_and_empty_prompt_are_checked(source_file, baseline, llm_client):
    for kwargs in ({"source_urls": []}, {"source_names": []}, {"instructions": "  "}):
        with pytest.raises(ValueError):
            discovery.discover_rules([source_file], baseline, llm_client, **kwargs)
    with pytest.raises(ValueError, match="at least one"):
        discovery.discover_rules([], baseline, llm_client)


def test_default_report_directory_is_external_and_not_hash_addressed(baseline, tmp_path, llm_client, monkeypatch):
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(tmp_path / "datasets"))
    monkeypatch.delenv("CARELOOP_ARTIFACT_DIR", raising=False)
    report = discovery.propose_rules(TEXT, {"path": "guideline.txt"}, baseline, llm_client)
    output = discovery.write_discovery_report(report)
    assert output.parent.parent == tmp_path / "datasets/outputs/knowledge-discovery"
    assert output.stat().st_mode & 0o777 == 0o600
    assert discovery.write_discovery_report(report) != output


@pytest.mark.parametrize("document", [[], {}, {"dsl_version": "1.0", "rules": [None]},
                                      {"dsl_version": "1.0", "rules": [{"rule_id": "x", "actions": [None]}]}])
def test_invalid_baseline_is_not_silently_ignored(document, llm_client):
    with pytest.raises(ValueError):
        discovery.propose_rules(TEXT, {"path": "guideline.txt"}, document, llm_client)


def test_duplicate_baseline_rule_ids_are_rejected(baseline, llm_client):
    baseline["rules"].append(baseline["rules"][0])
    with pytest.raises(ValueError, match="unique"):
        discovery.propose_rules(TEXT, {"path": "guideline.txt"}, baseline, llm_client)
