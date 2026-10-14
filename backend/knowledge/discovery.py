"""Propose nutrition rules from verified guideline files without changing live knowledge.

Candidates are review artifacts, not executable rulebooks or patient envelopes.
Only KDIGO protein and sodium recommendations have numeric mapping adapters.
Their exceptions and unresolved DSL semantics always block automatic activation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.knowledge.validation import content_hash
from backend.storage_paths import artifact_dir

KDIGO_PATH = "raw/guidelines/kdigo_2024_ckd.pdf"
KDIGO_URL = "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf"
GENERATOR = "kdigo-nutrition-v1"
_HEADING = re.compile(r"(?m)^[ \t]*(Recommendation|Practice Point)\s+(\d+(?:\.\d+)+):[ \t]*")


@dataclass(frozen=True)
class EvidenceExcerpt:
    statement_type: str
    section: str
    pdf_page: int
    start: int
    end: int
    quote: str

    def document(self) -> dict:
        return {"statement_type": self.statement_type, "section": self.section,
                "pdf_page": self.pdf_page, "page_text_start": self.start,
                "page_text_end": self.end, "quote": self.quote}


@dataclass(frozen=True)
class RecommendationMapping:
    section: str
    nutrient: str
    pattern: str
    kind: str
    source_unit: str
    output_basis: str
    scale: float
    source_operator: str
    caveats: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]


_MAPPINGS = (
    RecommendationMapping(
        section="3.3.1.1", nutrient="protein_g",
        pattern=r"We suggest maintaining a protein intake of (?P<value>\d+(?:\.\d+)?) "
                r"g/kg body weight/d in adults with CKD G3[–-]G5 \((?P<grade>\d[A-D])\)\.",
        kind="TARGET", source_unit="g/kg body weight/d", output_basis="g_per_kg_per_day",
        scale=1, source_operator="maintain",
        caveats=(("3.3.1.3", "metabolically unstable"),
                 ("3.3.1.4", "children"), ("3.3.1.5", "frailty and sarcopenia")),
        blockers=(
            "Review metabolic instability, frailty and sarcopenia. Current rule conditions do not represent these exclusions.",
            "Keep protein as a soft TARGET, not an inferred MIN floor or hard MAX ceiling.",
            "Confirm body-weight basis and conversion to daily grams before writing executable actions.",
        ),
    ),
    RecommendationMapping(
        section="3.3.2.1", nutrient="sodium_mg",
        pattern=r"We suggest that sodium intake be <(?P<value>\d+(?:\.\d+)?) g of sodium per day "
                r"\(or <\d+(?:\.\d+)? mmol of sodium per day, or <\d+(?:\.\d+)? g of sodium chloride "
                r"per day\) in people with CKD \((?P<grade>\d[A-D])\)\.",
        kind="MAX", source_unit="g sodium/day", output_basis="mg_per_day",
        scale=1000, source_operator="<",
        caveats=(("3.3.2.1", "sodium-wasting nephropathy"), ("3.3.2.2", "children")),
        blockers=(
            "Review sodium-wasting nephropathy. Current rule conditions do not represent this exception.",
            "The source uses strict '<'. CareLoop MAX ceilings allow equality, so boundary semantics require review.",
            "A guideline recommendation is not automatically a hard clinical ceiling. Review the proposed MAX mapping.",
        ),
    ),
)


def _verified_pdf(research_dir: Path) -> tuple[bytes, dict]:
    """Verify recorded bytes and source identity, not publisher authenticity or clinical validity."""
    manifest = json.loads((research_dir / "manifest.json").read_text())
    if not isinstance(manifest, list) or any(not isinstance(entry, dict) for entry in manifest):
        raise ValueError("Research manifest must be a list of source records")
    matches = [entry for entry in manifest if entry.get("path") == KDIGO_PATH]
    if len(matches) != 1:
        raise ValueError("Manifest must contain exactly one KDIGO guideline record")
    record = matches[0]
    if record.get("status") != "downloaded" or record.get("source_url") != KDIGO_URL:
        raise ValueError("KDIGO source must be downloaded from the supported guideline URL")
    path = research_dir / KDIGO_PATH
    payload = path.read_bytes()
    if not payload.startswith(b"%PDF"):
        raise ValueError("KDIGO source is not a PDF")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != record.get("sha256") or type(record.get("bytes")) is not int or len(payload) != record["bytes"]:
        raise ValueError("KDIGO source size/hash does not match the download manifest")
    return payload, {"path": KDIGO_PATH, "source_url": KDIGO_URL, "sha256": digest,
                  "bytes": record["bytes"], "verification": "manifest_size_and_sha256"}


def extract_statements(text: str) -> list[EvidenceExcerpt]:
    """Retain exact spans and one-based PDF pages from pdftotext's layout output.

    Repeated summary/body statements are kept for mapping-consistency checks.
    Quotes describe extracted PDF text, not a claim of OCR or layout fidelity.
    """
    statements = []
    for page_number, page in enumerate(text.split("\f"), start=1):
        headings = list(_HEADING.finditer(page))
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(page)
            block = page[heading.end():end]
            blank = re.search(r"\n[ \t]*\n", block)
            if blank:
                end = heading.end() + blank.start()
            quote = page[heading.start():end].strip()
            start = page.find(quote, heading.start(), end) if quote else heading.start()
            statements.append(EvidenceExcerpt(heading[1], heading[2], page_number,
                                               start, start + len(quote), quote))
    return statements


def _mapped_constraint(mapping: RecommendationMapping, quote: str) -> dict | None:
    normalized = " ".join(quote.split())
    prefix = re.escape(f"Recommendation {mapping.section}: ")
    match = re.match(prefix + mapping.pattern, normalized)
    if match is None:
        return None
    source_value = float(match["value"])
    value = source_value * mapping.scale
    if not math.isfinite(value) or value <= 0:
        return None
    return {"nutrient": mapping.nutrient, "kind": mapping.kind, "value": value,
            "basis": mapping.output_basis, "source_value": source_value,
            "source_unit": mapping.source_unit, "source_operator": mapping.source_operator,
            "evidence_grade": match["grade"]}


def _related_rules(rules_document: dict, nutrient: str) -> list[dict]:
    """Show same-nutrient rules without assuming their patient scopes overlap."""
    related = []
    for rule in rules_document["rules"]:
        actions = [action for action in rule["actions"]
                   if action.get("type") == "set_constraint" and action.get("nutrient") == nutrient]
        if actions:
            related.append({"rule_id": rule["rule_id"], "priority": rule.get("priority"),
                            "conditions": rule.get("conditions", []), "actions": actions,
                            "review": "Compare scope, units, constraint kind, value, priority and citation. No replacement was made."})
    return sorted(related, key=lambda rule: rule["rule_id"])


def propose_rules(text: str, source: dict, rules_document: dict) -> dict:
    """Build deterministic, blocked candidates from supported recommendations.

    Numeric suggestions require recognized wording. Unknown or contradictory
    passages retain their evidence but get no numeric mapping. Existing rules
    and patient scope gates are never modified or evaluated by discovery.
    """
    if not isinstance(rules_document, dict) or rules_document.get("dsl_version") != "1.0":
        raise ValueError("Discovery requires a CareLoop DSL 1.0 baseline rulebook")
    rules = rules_document.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Baseline rules must be a nonempty list")
    ids = set()
    for rule in rules:
        if (not isinstance(rule, dict) or not isinstance(rule.get("rule_id"), str)
                or not rule["rule_id"] or rule["rule_id"] in ids
                or not isinstance(rule.get("actions"), list)
                or any(not isinstance(action, dict) for action in rule["actions"])):
            raise ValueError("Baseline rules require unique IDs and action objects")
        ids.add(rule["rule_id"])
    baseline_hash = content_hash(rules_document)
    statements = extract_statements(text)
    candidates, missing = [], []
    for mapping in _MAPPINGS:
        matches = [item for item in statements
                   if item.statement_type == "Recommendation" and item.section == mapping.section]
        if not matches:
            missing.append(mapping.section)
            continue
        mapped = [_mapped_constraint(mapping, item.quote) for item in matches]
        recognized = [item for item in mapped if item is not None]
        suggested = recognized[0] if recognized else None
        blockers = list(mapping.blockers)
        if not recognized:
            blockers.append("Recommendation wording is unsupported. A reviewer must interpret the source without an inferred value.")
        elif any(item != suggested for item in recognized):
            suggested = None
            blockers.append("Repeated recommendation statements disagree. Resolve source values before mapping.")
        caveat_evidence = []
        for section, phrase in mapping.caveats:
            excerpts = [item for item in statements if item.statement_type == "Practice Point"
                        and item.section == section and phrase in " ".join(item.quote.split()).lower()]
            if excerpts:
                caveat_evidence.append(excerpts[0].document())
            else:
                blockers.append(f"Required caveat was not found: Practice Point {section} ({phrase}). Check the PDF.")
        candidate = {
            "status": "NEEDS_REVIEW", "guideline": "KDIGO 2024 CKD", "section": mapping.section,
            "source_population": "Adults with CKD G3–G5" if mapping.nutrient == "protein_g" else "People with CKD",
            "proposed_careloop_scope": {
                "age_min": 18, "diagnoses": ["CKD_stage_3", "CKD_stage_4"],
                "preserve_scope_exclusions": ["pregnancy", "paediatric", "dialysis", "CKD_stage_5", "egfr_below_15"],
                "review_required": True,
            },
            "suggested_constraint": suggested,
            "evidence": [item.document() for item in matches], "caveat_evidence": caveat_evidence,
            "review_blockers": blockers, "related_rules": _related_rules(rules_document, mapping.nutrient),
            "executable_rule": None, "automatic_activation_allowed": False,
        }
        candidate["candidate_id"] = "KDIGO-2024-" + mapping.section.replace(".", "-") + "-" + content_hash(
            {"generator": GENERATOR, "source": source, "section": mapping.section})[:16]
        candidates.append(candidate)
    supported = {mapping.section for mapping in _MAPPINGS}
    return {"schema_version": "1.0", "generator": GENERATOR, "source": source,
            "extraction": "pdftotext -layout", "baseline_rules_sha256": baseline_hash,
            "candidates": candidates, "missing_supported_sections": missing,
            "unsupported_nutrition_sections": sorted({item.section for item in statements
                if item.statement_type == "Recommendation" and item.section.startswith("3.3.")
                and item.section not in supported}),
            "limitations": [
                "Discovery supports KDIGO 2024 protein and sodium recommendations only. It is not clinical validation.",
                "Manifest checks detect changed bytes, not publisher authenticity. Check the original PDF and its exceptions.",
                "PDF layout extraction can omit or mix columns. Review all quoted passages against their PDF pages.",
                "NHANES, MIMIC, food composition and observational associations are not prescribing evidence adapters.",
                "These candidates cannot be imported as an executable rulebook. Resolve blockers before authoring a draft.",
            ]}


def discover_rules(research_dir: Path, rules_document: dict) -> dict:
    """Verify the downloaded PDF and extract fresh text, never trusting cached staging quotes."""
    payload, source = _verified_pdf(research_dir)
    try:
        result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=payload,
                                capture_output=True, check=True, timeout=120)
    except FileNotFoundError as error:
        raise RuntimeError("Install pdftotext (Poppler tools) before running discovery") from error
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Guideline PDF extraction failed or timed out") from error
    report = propose_rules(result.stdout.decode("utf-8"), source, rules_document)
    if not report["candidates"]:
        raise ValueError("No supported guideline recommendations found. Check source version and extraction")
    return report


def write_discovery_report(report: dict, out_dir: Path | None = None) -> Path:
    """Write an external content-addressed report. Identical retries reuse it without overwrite."""
    destination = (out_dir or artifact_dir("knowledge-discovery") / content_hash(report)).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if destination == checkout or checkout in destination.parents:
        raise ValueError("Discovery output directory must be outside the code checkout")
    output = destination / "rule_candidates.json"
    payload = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if destination.exists():
        if output.is_file() and output.read_text() == payload:
            return output
        raise ValueError("Discovery output already exists with different or incomplete content. Use a new directory")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    output.chmod(0o600)
    return output
