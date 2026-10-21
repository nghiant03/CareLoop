"""Discovery preserves evidence and emits candidates without clinical or journal writes."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.knowledge import discovery
from backend.knowledge.__main__ import main
from backend.knowledge.validation import validate_documents

PROTEIN = """Recommendation 3.3.1.1: We suggest maintaining a protein intake of 0.8 g/kg body weight/d in adults with
 CKD G3–G5 (2C).

Practice Point 3.3.1.3: Do not prescribe low- or very low–protein diets in metabolically unstable people with CKD.
Practice Point 3.3.1.4: Do not restrict protein intake in children with CKD due to the risk of growth impairment.
Practice Point 3.3.1.5: In older adults with underlying conditions such as frailty and sarcopenia, consider higher protein
 and calorie dietary targets.
"""
SODIUM = """Recommendation 3.3.2.1: We suggest that sodium intake be <2 g of sodium per day (or <90 mmol of sodium
 per day, or <5 g of sodium chloride per day) in people with CKD (2C).
"""
SODIUM_CAVEATS = """Practice Point 3.3.2.1: Dietary sodium restriction is usually not appropriate for patients with sodium-wasting nephropathy

Practice Point 3.3.2.2: Follow age-based Recommended Daily Intake when counseling about sodium intake for children with CKD.
"""
TEXT = PROTEIN + "\n" + SODIUM + "\f" + SODIUM_CAVEATS
SOURCE = {"path": discovery.KDIGO_PATH, "source_url": discovery.KDIGO_URL, "sha256": "a" * 64}


@pytest.fixture
def baseline():
    return {"dsl_version": "1.0", "rules": [
        {"rule_id": "CKD-PROTEIN", "priority": 90,
         "conditions": [{"field": "diagnoses", "op": "in", "value": ["CKD_stage_3", "CKD_stage_4"]}],
         "actions": [{"type": "set_constraint", "nutrient": "protein_g", "kind": "max", "value": 0.8}]},
        {"rule_id": "CKD-SODIUM", "priority": 90, "conditions": [],
         "actions": [{"type": "set_constraint", "nutrient": "sodium_mg", "kind": "max", "value": 2000}]},
    ]}


@pytest.fixture
def research(tmp_path, monkeypatch):
    root = tmp_path / "research"
    pdf = root / discovery.KDIGO_PATH
    pdf.parent.mkdir(parents=True)
    payload = b"%PDF-synthetic-source-for-extraction-tests"
    pdf.write_bytes(payload)
    manifest = [{"path": discovery.KDIGO_PATH, "source_url": discovery.KDIGO_URL,
                 "status": "downloaded", "bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}]
    (root / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(discovery.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=TEXT.encode()))
    return root


def test_numeric_proposals_retain_units_grade_and_scope(baseline):
    original = copy.deepcopy(baseline)
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    protein, sodium = report["candidates"]
    assert protein["suggested_constraint"] == {
        "nutrient": "protein_g", "kind": "TARGET", "value": 0.8,
        "basis": "g_per_kg_per_day", "source_value": 0.8,
        "source_unit": "g/kg body weight/d", "source_operator": "maintain", "evidence_grade": "2C",
    }
    assert sodium["suggested_constraint"]["value"] == 2000
    assert sodium["suggested_constraint"]["source_operator"] == "<"
    assert sodium["suggested_constraint"]["basis"] == "mg_per_day"
    for candidate in report["candidates"]:
        assert candidate["status"] == "NEEDS_REVIEW"
        assert candidate["automatic_activation_allowed"] is False
        assert candidate["executable_rule"] is None
        assert candidate["proposed_careloop_scope"]["diagnoses"] == ["CKD_stage_3", "CKD_stage_4"]
        assert candidate["review_blockers"]
    assert baseline == original


def test_all_quotes_are_exact_page_spans_and_caveats_cross_pages(baseline):
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    pages = TEXT.split("\f")
    for candidate in report["candidates"]:
        for evidence in candidate["evidence"] + candidate["caveat_evidence"]:
            page = pages[evidence["pdf_page"] - 1]
            assert page[evidence["page_text_start"]:evidence["page_text_end"]] == evidence["quote"]
    protein, sodium = report["candidates"]
    assert {item["section"] for item in protein["caveat_evidence"]} == {"3.3.1.3", "3.3.1.4", "3.3.1.5"}
    assert all(item["pdf_page"] == 2 for item in sodium["caveat_evidence"])
    assert any("equality" in blocker for blocker in sodium["review_blockers"])


def test_existing_rules_are_compared_not_replaced(baseline):
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    assert report["baseline_rules_sha256"] == discovery.content_hash(baseline)
    related = report["candidates"][0]["related_rules"]
    assert related[0]["rule_id"] == "CKD-PROTEIN"
    assert related[0]["actions"][0]["kind"] == "max"
    assert related[0]["conditions"] == baseline["rules"][0]["conditions"]
    with pytest.raises(ValueError, match="dsl_version"):
        validate_documents(report, [])


def test_deterministic_reruns_and_source_bound_candidate_ids(baseline):
    first = discovery.propose_rules(TEXT, SOURCE, baseline)
    assert first == discovery.propose_rules(TEXT, SOURCE, baseline)
    second = discovery.propose_rules(TEXT, {**SOURCE, "sha256": "b" * 64}, baseline)
    assert first["candidates"][0]["candidate_id"] != second["candidates"][0]["candidate_id"]
    baseline["rules"][0]["priority"] = 80
    updated = discovery.propose_rules(TEXT, SOURCE, baseline)
    assert first["baseline_rules_sha256"] != updated["baseline_rules_sha256"]
    assert first["candidates"][0]["candidate_id"] == updated["candidates"][0]["candidate_id"]


@pytest.mark.parametrize("old,new", [("0.8 g/kg", "0.8 mg/kg"),
                                      ("maintaining a protein", "avoiding a protein"),
                                      ("CKD G3–G5", "healthy adults"),
                                      ("0.8 g/kg", "0 g/kg")])
def test_unrecognized_or_zero_protein_never_gets_numeric_mapping(baseline, old, new):
    report = discovery.propose_rules(TEXT.replace(old, new), SOURCE, baseline)
    candidate = report["candidates"][0]
    assert candidate["suggested_constraint"] is None
    assert candidate["evidence"]
    assert any("unsupported" in blocker for blocker in candidate["review_blockers"])


def test_sodium_does_not_confuse_salt_and_sodium(baseline):
    report = discovery.propose_rules(TEXT.replace("<2 g of sodium", "<2 g of salt"), SOURCE, baseline)
    assert report["candidates"][1]["suggested_constraint"] is None


def test_unknown_nutrition_recommendations_are_disclosed_not_invented(baseline):
    text = TEXT + "\n\nRecommendation 3.3.9.1: A new nutrition recommendation.\n"
    report = discovery.propose_rules(text, SOURCE, baseline)
    assert len(report["candidates"]) == 2
    assert report["unsupported_nutrition_sections"] == ["3.3.9.1"]


def test_missing_caveats_and_recommendations_are_disclosed(baseline):
    report = discovery.propose_rules(SODIUM, SOURCE, baseline)
    assert report["missing_supported_sections"] == ["3.3.1.1"]
    candidate = report["candidates"][0]
    assert not candidate["caveat_evidence"]
    assert sum("not found" in blocker for blocker in candidate["review_blockers"]) == 2


def test_repeated_recommendations_do_not_duplicate_candidates(baseline):
    report = discovery.propose_rules(TEXT + "\f" + PROTEIN, SOURCE, baseline)
    assert len(report["candidates"]) == 2
    assert len(report["candidates"][0]["evidence"]) == 2
    assert report["candidates"][0]["suggested_constraint"]["value"] == 0.8


def test_contradictory_repeated_values_block_numeric_mapping(baseline):
    report = discovery.propose_rules(TEXT + "\f" + PROTEIN.replace("0.8", "0.9"), SOURCE, baseline)
    assert report["candidates"][0]["suggested_constraint"] is None
    assert any("disagree" in blocker for blocker in report["candidates"][0]["review_blockers"])


@pytest.mark.parametrize("field,value", [("sha256", "bad"), ("bytes", 1),
                                        ("bytes", True), ("status", "unavailable"),
                                        ("source_url", "https://example.invalid/guideline.pdf")])
def test_source_verification_fails_closed(research, baseline, field, value):
    manifest = json.loads((research / "manifest.json").read_text())
    manifest[0][field] = value
    (research / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        discovery.discover_rules(research, baseline)


def test_pdf_bytes_and_duplicate_manifest_entries_are_rejected(research, baseline):
    pdf = research / discovery.KDIGO_PATH
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash"):
        discovery.discover_rules(research, baseline)
    manifest = json.loads((research / "manifest.json").read_text())
    (research / "manifest.json").write_text(json.dumps(manifest * 2))
    with pytest.raises(ValueError, match="exactly one"):
        discovery.discover_rules(research, baseline)


def test_discovery_extracts_verified_pdf_not_cached_text(research, baseline):
    (research / "raw/guidelines/kdigo_2024_ckd.txt").write_text("untrusted cached evidence")
    report = discovery.discover_rules(research, baseline)
    assert len(report["candidates"]) == 2
    assert report["source"]["verification"] == "manifest_size_and_sha256"


def test_missing_extractor_and_no_supported_evidence_are_errors(research, baseline, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("pdftotext")
    monkeypatch.setattr(discovery.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="Install pdftotext"):
        discovery.discover_rules(research, baseline)
    monkeypatch.setattr(discovery.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"No statements"))
    with pytest.raises(ValueError, match="No supported"):
        discovery.discover_rules(research, baseline)


def test_report_retries_are_idempotent_and_do_not_overwrite(baseline, tmp_path):
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    destination = tmp_path / "output"
    output = discovery.write_discovery_report(report, destination)
    before = output.stat().st_mtime_ns
    assert discovery.write_discovery_report(report, destination) == output
    assert output.stat().st_mtime_ns == before
    output.write_text("operator edits")
    with pytest.raises(ValueError, match="already exists"):
        discovery.write_discovery_report(report, destination)
    assert output.read_text() == "operator edits"


def test_report_refuses_checkout_and_symlinks_into_checkout(baseline, tmp_path):
    report = discovery.propose_rules(TEXT, SOURCE, baseline)
    checkout = Path(__file__).resolve().parents[3]
    for path in (checkout, checkout / "artifacts/discovery"):
        with pytest.raises(ValueError, match="outside"):
            discovery.write_discovery_report(report, path)
    link = tmp_path / "symlink"
    link.symlink_to(checkout, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        discovery.write_discovery_report(report, link / "discovery")


def test_cli_discovery_never_opens_or_creates_a_database(research, baseline, tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / "rules.json"
    baseline_path.write_text(json.dumps(baseline))
    database = tmp_path / "must-not-exist.sqlite3"
    monkeypatch.setenv("CARELOOP_KNOWLEDGE_DATABASE_URL_FILE", str(tmp_path / "missing-secret"))
    monkeypatch.setenv("CARELOOP_APP_DB", str(database))
    def forbidden(*args, **kwargs):
        raise AssertionError("Discovery must not construct a knowledge store")
    monkeypatch.setattr("backend.knowledge.__main__.KnowledgeStore", forbidden)
    arguments = ["discover", "--research-dir", str(research),
                 "--rules-file", str(baseline_path), "--out-dir", str(tmp_path / "output")]
    assert main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["database_writes"] is False
    assert summary["status"] == "NEEDS_REVIEW"
    assert summary["candidates"] == 2
    assert not database.exists()


def test_cli_errors_do_not_write_partial_report(research, baseline, tmp_path, monkeypatch):
    baseline_path = tmp_path / "rules.json"
    baseline_path.write_text(json.dumps(baseline))
    monkeypatch.setattr(discovery.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"No statements"))
    with pytest.raises(SystemExit) as error:
        main(["discover", "--research-dir", str(research), "--rules-file", str(baseline_path),
              "--out-dir", str(tmp_path / "output")])
    assert error.value.code == 1
    assert not (tmp_path / "output").exists()
