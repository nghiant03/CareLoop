"""Verify discovery extraction boundaries and repeat-safe external report storage."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from backend.knowledge import discovery
from backend.knowledge.test_discovery import SOURCE, TEXT, baseline, research


def test_extractor_receives_the_verified_bytes(research, baseline, monkeypatch):
    pdf = research / discovery.KDIGO_PATH
    expected = pdf.read_bytes()

    def extract(command, **kwargs):
        assert command == ["pdftotext", "-layout", "-", "-"]
        assert kwargs["input"] == expected
        assert kwargs["timeout"] == 120
        pdf.write_bytes(b"%PDF-changed-after-verification")
        return SimpleNamespace(stdout=TEXT.encode())

    monkeypatch.setattr(discovery.subprocess, "run", extract)
    report = discovery.discover_rules(research, baseline)
    assert report["source"]["sha256"] == discovery.hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, ["pdftotext"]),
                                  subprocess.TimeoutExpired(["pdftotext"], 120)])
def test_extraction_failure_is_not_a_successful_empty_report(research, baseline, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(discovery.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="failed or timed out"):
        discovery.discover_rules(research, baseline)


@pytest.mark.parametrize("manifest", [{}, [], ["not a source record"]])
def test_malformed_and_missing_manifests_are_rejected(research, baseline, manifest):
    (research / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        discovery.discover_rules(research, baseline)


def test_non_pdf_data_is_rejected_before_extraction(research, baseline):
    (research / discovery.KDIGO_PATH).write_bytes(b"HTML access page")
    with pytest.raises(ValueError, match="not a PDF"):
        discovery.discover_rules(research, baseline)


def test_default_report_directory_is_external_and_content_addressed(baseline, tmp_path, monkeypatch):
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(tmp_path / "datasets"))
    monkeypatch.delenv("CARELOOP_ARTIFACT_DIR", raising=False)
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    output = discovery.write_discovery_report(report)
    assert output == tmp_path / "datasets/outputs/knowledge-discovery" / discovery.content_hash(report) / "rule_candidates.json"
    assert discovery.write_discovery_report(report) == output
    assert output.stat().st_mode & 0o777 == 0o600


def test_partial_report_directory_is_preserved(baseline, tmp_path):
    destination = tmp_path / "partial"
    destination.mkdir()
    (destination / "notes.txt").write_text("operator notes")
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    with pytest.raises(ValueError, match="incomplete"):
        discovery.write_discovery_report(report, destination)
    assert (destination / "notes.txt").read_text() == "operator notes"
    assert not (destination / "rule_candidates.json").exists()


@pytest.mark.parametrize("document", [[], {}, {"dsl_version": "1.0", "rules": []},
                                      {"dsl_version": "1.0", "rules": [None]},
                                      {"dsl_version": "1.0", "rules": [{"rule_id": "x", "actions": [None]}]}])
def test_invalid_baseline_is_not_silently_ignored(document):
    with pytest.raises(ValueError):
        discovery.propose_rules(TEXT, SOURCE, document)


def test_duplicate_baseline_rule_ids_are_rejected(baseline):
    baseline["rules"].append(baseline["rules"][0])
    with pytest.raises(ValueError, match="unique"):
        discovery.propose_rules(TEXT, SOURCE, baseline)


def test_quoted_or_negated_advice_inside_a_recommendation_is_not_mapped(baseline):
    text = TEXT.replace("We suggest maintaining", "Do not follow this quoted advice: We suggest maintaining")
    report = discovery.propose_rules(text, SOURCE, baseline)
    assert report["candidates"][0]["suggested_constraint"] is None
