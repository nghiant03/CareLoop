import copy
import json
from pathlib import Path

import pytest

from backend.knowledge import discovery
from backend.knowledge.validation import validate_documents
from tests.backend.knowledge.conftest import FIBRE, SODIUM, TEXT, FakeDiscoveryClient

SOURCE = {"path": "another-guideline.pdf", "guideline": "Independent guideline", "source_url": "https://example.org/guideline"}


def test_candidates_come_from_model_not_fixed_kdigo_wording(baseline, llm_client):
    original = copy.deepcopy(baseline)
    report = discovery.propose_rules(TEXT, SOURCE, baseline, llm_client)
    assert len(llm_client.calls) == 1
    assert llm_client.calls[0]["source_text"] == TEXT
    assert len(report["candidates"]) == 2
    fibre, sodium = report["candidates"]
    assert fibre["suggested_constraint"] == {"nutrient": "fiber_g", "kind": "TARGET", "value": 28, "basis": "g_per_day"}
    assert sodium["suggested_constraint"]["source_operator"] == "limit"
    assert sodium["suggested_constraint"]["source_unit"] == "mg/day"
    for candidate in report["candidates"]:
        assert candidate["status"] == "NEEDS_REVIEW"
        assert candidate["automatic_activation_allowed"] is False
        assert candidate["executable_rule"] is None
        assert candidate["review_blockers"]
        evidence = candidate["evidence"][0]
        assert TEXT[evidence["text_start"]:evidence["text_end"]] == evidence["quote"]
        assert evidence["source"] == SOURCE
    assert sodium["evidence"][0]["pdf_page"] == 2
    assert baseline == original
    assert fibre["related_rules"][0]["rule_id"] == "FIBRE-BASELINE"
    with pytest.raises(ValueError, match="dsl_version"):
        validate_documents(report, [])


def test_discovery_needs_no_manifest_or_hashes(source_file, baseline, llm_client):
    (source_file.parent / "manifest.json").write_text("not even JSON")
    source_file.write_bytes(source_file.read_bytes() + b"changed content")
    report = discovery.discover_rules([source_file], baseline, llm_client)
    assert report["sources"][0]["path"] == str(source_file)
    assert report["sources"][0]["candidate_count"] == 2
    assert not any(key in json.dumps(report) for key in ('"sha256"', '"baseline_rules_sha256"', '"verification"'))


def test_multiple_non_kdigo_sources_and_source_urls(tmp_path, baseline, llm_client):
    first = tmp_path / "public-health.md"
    second = tmp_path / "another-society.txt"
    first.write_text(FIBRE["quote"])
    second.write_text(SODIUM["quote"])
    urls = ["https://example.org/public-health", "https://example.org/society"]
    report = discovery.discover_rules([first, second], baseline, llm_client, source_urls=urls)
    assert len(report["sources"]) == 2
    assert [source["source_url"] for source in report["sources"]] == urls
    assert [source["candidate_count"] for source in report["sources"]] == [1, 1]
    assert {candidate["guideline"] for candidate in report["candidates"]} == {"public-health", "another-society"}
    assert all("pdf_page" not in candidate["evidence"][0] for candidate in report["candidates"])


def test_html_is_parsed_without_executing_embedded_content(tmp_path, baseline, llm_client):
    path = tmp_path / "guideline.html"
    path.write_text(f"<style>ignore me</style><script>do not run me</script><p>{FIBRE['quote']}</p>")
    report = discovery.discover_rules([path], baseline, llm_client)
    assert len(report["candidates"]) == 1
    assert "ignore me" not in llm_client.calls[0]["source_text"]
    assert "do not run me" not in llm_client.calls[0]["source_text"]


def test_prompt_is_loaded_from_a_resource_and_can_be_overridden(tmp_path, source_file, baseline, llm_client):
    assert discovery.load_discovery_prompt() == discovery.DEFAULT_PROMPT.read_text()
    override = tmp_path / "instructions.md"
    override.write_text("Extract only explicitly stated quantitative nutrition recommendations.")
    instructions = discovery.load_discovery_prompt(override)
    report = discovery.discover_rules([source_file], baseline, llm_client, instructions=instructions)
    assert all(call["instructions"] == instructions for call in llm_client.calls)
    assert report["extraction"]["instructions"] == instructions
    assert report["extraction"]["model"] == "test-model"


def test_chunking_is_bounded_overlapping_and_deduplicates(baseline, llm_client):
    text = (" " * (discovery.CHUNK_CHARS - 1000) + FIBRE["quote"]
            + " " * discovery.CHUNK_CHARS)
    report = discovery.propose_rules(text, SOURCE, baseline, llm_client)
    assert len(llm_client.calls) >= 2
    assert all(len(call["source_text"]) <= discovery.CHUNK_CHARS for call in llm_client.calls)
    assert len(report["candidates"]) == 1
    assert sum(FIBRE["quote"] in call["source_text"] for call in llm_client.calls) == 2


@pytest.mark.parametrize("field,value", [
    ("quote", "Fabricated advice that does not occur in this source"),
    ("value", 0), ("value", -1), ("value", True), ("value", float("inf")), ("value", 10**500),
    ("nutrient", "unsupported"), ("nutrient", []), ("kind", {}),
    ("kind", "MONITOR"), ("basis", ""), ("basis", None), ("caveats", "not a list"),
])
def test_invalid_model_candidates_are_not_accepted(baseline, field, value):
    client = FakeDiscoveryClient([{**FIBRE, field: value}])
    assert discovery.propose_rules(TEXT, SOURCE, baseline, client)["candidates"] == []


def test_empty_baseline_is_allowed_for_new_workspace(llm_client):
    report = discovery.propose_rules(TEXT, SOURCE, {"dsl_version": "1.0", "rules": []}, llm_client)
    assert all(not candidate["related_rules"] for candidate in report["candidates"])


def test_report_storage_does_not_overwrite_operator_work(baseline, llm_client, tmp_path):
    report = discovery.propose_rules(TEXT, SOURCE, baseline, llm_client)
    output = discovery.write_discovery_report(report, tmp_path / "output")
    before = output.stat().st_mtime_ns
    assert discovery.write_discovery_report(report, output.parent) == output
    assert output.stat().st_mtime_ns == before
    output.write_text("operator edits")
    with pytest.raises(ValueError, match="already exists"):
        discovery.write_discovery_report(report, output.parent)
    assert output.read_text() == "operator edits"


def test_report_refuses_checkout_and_symlinks(baseline, llm_client, tmp_path):
    report = discovery.propose_rules(TEXT, SOURCE, baseline, llm_client)
    checkout = Path(__file__).resolve().parents[3]
    link = tmp_path / "symlink"
    link.symlink_to(checkout, target_is_directory=True)
    for path in (checkout, checkout / "artifacts/discovery", link / "discovery"):
        with pytest.raises(ValueError, match="outside"):
            discovery.write_discovery_report(report, path)
