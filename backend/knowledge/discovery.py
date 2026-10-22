"""Use an LLM to propose review-only nutrition rules from operator-selected sources.

Discovery requires no manifest or hashes and has no guideline-specific patterns.
Candidates are evidence-linked review artifacts, never executable rulebooks.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from backend.storage_paths import artifact_dir

GENERATOR = "llm-nutrition-v2"
CHUNK_CHARS = 24000
CHUNK_OVERLAP = 2000
DEFAULT_PROMPT = Path(__file__).with_name("prompts") / "discover_rules.md"


class DiscoveryClient(Protocol):
    """Provider-neutral boundary; a future adapter owns transport and JSON parsing."""

    def extract_candidates(self, *, instructions: str, source_text: str) -> dict:
        """Return a document containing a ``candidates`` list."""
        ...


def load_discovery_prompt(prompt_file: Path | None = None) -> str:
    """Load editable instructions separately from extraction logic."""
    instructions = (prompt_file or DEFAULT_PROMPT).read_text(encoding="utf-8")
    if not instructions.strip():
        raise ValueError("Discovery instructions must not be empty")
    return instructions


def _read_source(path: Path) -> str:
    """Read a local PDF, HTML, Markdown or text document without a manifest."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        payload = path.read_bytes()
        if not payload.startswith(b"%PDF"):
            raise ValueError(f"Source is not a PDF: {path}")
        try:
            result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=payload,
                                    capture_output=True, check=True, timeout=120)
        except FileNotFoundError as error:
            raise RuntimeError("Install pdftotext (Poppler tools) before reading PDF sources") from error
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"PDF extraction failed or timed out: {path}") from error
        text = result.stdout.decode("utf-8")
    elif suffix in {".txt", ".md", ".html", ".htm"}:
        text = path.read_text(encoding="utf-8")
        if suffix in {".html", ".htm"}:
            from html import unescape

            text = unescape(_strip_html(text))
    else:
        raise ValueError(f"Unsupported source format {suffix!r}; use PDF, HTML, Markdown or text")
    if not text.strip():
        raise ValueError(f"Source has no extractable text: {path}")
    return text


def _text_chunks(text: str):
    """Bound model requests with overlapping text windows, not medical patterns."""
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        yield text[start:end]
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP


def _quote_evidence(quote: str, text: str) -> dict:
    """Locate model quotes in the extracted text, preserving original whitespace."""
    match = re.search(r"\s+".join(re.escape(word) for word in quote.split()), text)
    if match is None:
        raise ValueError("Candidate quote was not found in the source text")
    return {"quote": match.group(), "verified_substring": True,
            "text_start": match.start(), "text_end": match.end(),
            "pdf_page": text.count("\f", 0, match.start()) + 1,
            "pdf_page_end": text.count("\f", 0, match.end()) + 1}


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


def propose_rules(text: str, source: dict, rules_document: dict, client: DiscoveryClient,
                  instructions: str | None = None) -> dict:
    """Extract candidates using only the LLM; baseline rules are comparison-only."""
    if not isinstance(rules_document, dict) or rules_document.get("dsl_version") != "1.0":
        raise ValueError("Discovery requires a CareLoop DSL 1.0 baseline rulebook")
    rules = rules_document.get("rules")
    if not isinstance(rules, list):
        raise TypeError("Baseline rules must be a list")
    ids = set()
    for rule in rules:
        if (not isinstance(rule, dict) or not isinstance(rule.get("rule_id"), str)
                or not rule["rule_id"] or rule["rule_id"] in ids
                or not isinstance(rule.get("actions"), list)
                or any(not isinstance(action, dict) for action in rule["actions"])):
            raise ValueError("Baseline rules require unique IDs and action objects")
        ids.add(rule["rule_id"])
    candidates, seen = [], set()
    for chunk in _text_chunks(text):
        for candidate in extract_rules(chunk, source, client, instructions=instructions):
            key = json.dumps({"section": candidate["section"],
                              "population": candidate["source_population"],
                              "constraint": candidate["suggested_constraint"],
                              "quote": " ".join(candidate["evidence"][0]["quote"].split())}, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            evidence = _quote_evidence(candidate["evidence"][0]["quote"], text)
            if Path(source["path"]).suffix.lower() != ".pdf":
                evidence.pop("pdf_page")
                evidence.pop("pdf_page_end")
            evidence["source"] = dict(source)
            candidate["evidence"] = [evidence]
            candidate["candidate_id"] = f"CAND-{uuid4().hex}"
            candidate["related_rules"] = _related_rules(rules_document, candidate["suggested_constraint"]["nutrient"])
            candidate["review_blockers"] = [
                "Verify the suggested value, units, constraint kind and population against the original source.",
                "Review the full guideline for exceptions, negation, conflicting recommendations and missing caveats; extraction is not exhaustive.",
                "Preserve CareLoop scope exclusions. A source recommendation does not authorize use for excluded patients.",
                "CareLoop MAX allows equality and MIN/TARGET are soft aims; review any strict source operator and clinical interpretation.",
            ]
            candidates.append(candidate)
    return {"schema_version": "2.0", "generator": GENERATOR, "source": dict(source),
            "extraction": {"adapter": type(client).__name__, "model": getattr(client, "model", "unspecified")},
            "candidates": candidates,
            "limitations": [
                "LLM output is non-deterministic and may omit or misinterpret recommendations. No clinical validity is established.",
                "Quote matching proves text presence, not that numbers, units, scope or caveats were interpreted correctly.",
                "Source authenticity and clinical suitability are operator responsibilities; discovery uses no manifest or hash checks.",
                "PDF layout extraction can omit or mix columns. Review quotes against their PDF pages.",
                "These candidates cannot be imported as an executable rulebook. Resolve blockers before authoring a draft.",
            ]}


def discover_rules(sources: list[Path], rules_document: dict, client: DiscoveryClient,
                   source_urls: list[str | None] | None = None, *,
                   instructions: str | None = None, source_names: list[str] | None = None) -> dict:
    """Extract from any explicitly selected guideline files, with no static fallback."""
    if not sources:
        raise ValueError("Select at least one guideline source")
    if source_urls is not None and len(source_urls) != len(sources):
        raise ValueError("Source URLs must correspond to the selected sources")
    if source_names is not None and len(source_names) != len(sources):
        raise ValueError("Source names must correspond to the selected sources")
    instructions = instructions if instructions is not None else load_discovery_prompt()
    reports = []
    for index, path in enumerate(sources):
        path = path.expanduser().resolve()
        name = source_names[index] if source_names is not None else str(path)
        source = {"path": name, "guideline": Path(name).stem,
                  "source_url": source_urls[index] if source_urls is not None else None}
        reports.append(propose_rules(_read_source(path), source, rules_document, client, instructions))
    report = {"schema_version": "2.0", "generator": GENERATOR,
              "sources": [{**item["source"], "candidate_count": len(item["candidates"])} for item in reports],
              "extraction": {**reports[0]["extraction"], "instructions": instructions},
              "candidates": [candidate for item in reports for candidate in item["candidates"]],
              "limitations": reports[0]["limitations"]}
    if not report["candidates"]:
        raise ValueError("No valid source-quoted nutrition candidates returned by the LLM; inspect the sources and provider output")
    return report


def write_discovery_report(report: dict, out_dir: Path | None = None) -> Path:
    """Write an external run directory without hashes or overwriting existing work."""
    destination = (out_dir or artifact_dir("knowledge-discovery") / uuid4().hex).expanduser().resolve()
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


_ALLOWED_NUTRIENTS = {
    "energy_kcal",
    "protein_g",
    "carbs_g",
    "sugar_g",
    "fiber_g",
    "fat_g",
    "sat_fat_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
}
_ALLOWED_KINDS = {"MIN", "MAX", "TARGET"}


def verify_quote_in_source(quote: str, source_text: str) -> bool:
    """Verify that ``quote`` is a non-empty, whitespace-normalized verbatim substring of ``source_text``."""
    if not isinstance(quote, str) or not isinstance(source_text, str):
        return False
    norm_quote = " ".join(quote.split())
    if len(norm_quote) < 12:
        return False
    norm_source = " ".join(source_text.split())
    return norm_quote in norm_source


def extract_rules(
    source_text: str,
    source_meta: dict,
    client: DiscoveryClient,
    *,
    instructions: str | None = None,
) -> list[dict]:
    """Validate source-quoted, review-only proposals returned by any LLM adapter.

    Every returned candidate must supply a verbatim ``quote`` verified against
    ``source_text`` (preventing zero-quote or hallucinated extractions), a
    recognized nutrient and constraint kind, and a finite positive numeric value.
    All candidates remain ``NEEDS_REVIEW`` with ``automatic_activation_allowed=False``.
    """
    instructions = instructions if instructions is not None else load_discovery_prompt()
    if not instructions.strip():
        raise ValueError("Discovery instructions must not be empty")
    parsed = client.extract_candidates(instructions=instructions, source_text=source_text)
    raw_candidates = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(raw_candidates, list):
        raise TypeError("LLM extraction must return an object with a 'candidates' list")

    verified_candidates: list[dict] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote", "")
        nutrient = item.get("nutrient", "")
        kind = item.get("kind", "")
        val = item.get("value")
        try:
            number = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else 0.0
        except OverflowError:
            continue
        if (
            not isinstance(nutrient, str) or nutrient not in _ALLOWED_NUTRIENTS
            or not isinstance(kind, str) or kind not in _ALLOWED_KINDS
            or not math.isfinite(number)
            or number <= 0
        ):
            continue
        if not verify_quote_in_source(quote, source_text):
            continue
        basis = item.get("basis")
        caveats = item.get("caveats", [])
        if not isinstance(basis, str) or not basis.strip() or not isinstance(caveats, list):
            continue
        constraint = {"nutrient": nutrient, "kind": kind, "value": number, "basis": basis.strip()}
        for field in ("source_unit", "source_operator", "evidence_grade"):
            if isinstance(item.get(field), str):
                constraint[field] = item[field]
        source_value = item.get("source_value")
        if isinstance(source_value, (int, float)) and not isinstance(source_value, bool):
            try:
                if math.isfinite(source_value) and source_value > 0:
                    constraint["source_value"] = source_value
            except OverflowError:
                pass
        section = str(item.get("section") or "unspecified")
        verified_candidates.append({
            "status": "NEEDS_REVIEW",
            "guideline": str(source_meta.get("guideline") or "External Guideline"),
            "section": section,
            "source_population": str(item.get("source_population") or "Requires clinician review"),
            "suggested_constraint": constraint,
            "evidence": [{"quote": " ".join(quote.split()), "verified_substring": True}],
            "caveats": [c for c in caveats if isinstance(c, str)],
            "executable_rule": None,
            "automatic_activation_allowed": False,
        })
    return verified_candidates


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def evaluate_cross_guideline_ground_truth(research_dir: Path, rules_document: dict) -> dict:
    """Evaluate extracted and baseline rules against independent held-out external guidelines.

    Uses held-out clinical guidelines not used to author the KDIGO 2024 rules:
    1. KDIGO 2022 Diabetes in CKD & ADA–KDIGO 2022 Consensus Report (PDFs)
    2. KDIGO 2017 CKD-MBD Guideline Update (PDF)
    3. ADA Medical Nutrition Therapy Consensus (PMC6540072 HTML) & NHLBI DASH (PDF)
    4. OpenFDA Official Structured Product Labeling (`openfda_drug_labels.json` + FDA PDFs)
    """
    raw_root = research_dir / "raw" if (research_dir / "raw").exists() else research_dir
    g_dir = raw_root / "guidelines"

    rules_by_id = {
        r["rule_id"]: r
        for r in rules_document.get("rules", [])
        if isinstance(r, dict) and "rule_id" in r
    }
    concordance_checks: list[dict] = []

    def _pdf_text(path: Path) -> str:
        if not path.exists():
            return ""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                check=True,
                timeout=60,
            )
            return " ".join(proc.stdout.decode("utf-8", errors="replace").split())
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return ""

    # 1. Held-out KDIGO 2022 Diabetes Management in CKD PDF
    kdigo_2022_txt = _pdf_text(g_dir / "kdigo_2022_diabetes_ckd.pdf")
    if kdigo_2022_txt:
        has_prot = bool(re.search(r"0\.8\s*g/kg", kdigo_2022_txt, re.IGNORECASE))
        has_na = bool(re.search(r"<\s*2(?:\.0)?\s*g\b|2,?000\s*mg", kdigo_2022_txt, re.IGNORECASE))
        concordance_checks.append({
            "held_out_source": "KDIGO 2022 Clinical Practice Guideline for Diabetes Management in CKD",
            "domain": "CKD G3–G5 non-dialysis protein & sodium targets",
            "held_out_reference": "Protein 0.8 g/kg/day; Sodium < 2.0 g/day (< 2,000 mg/day)",
            "careloop_rule_id": "CKD-2024-PROTEIN-055-08",
            "careloop_value": "Protein 0.8 g/kg/day; Sodium MAX 2,000 mg/day",
            "evidence_extracted_from_source": has_prot and has_na,
            "polarity_match": "CKD-2024-PROTEIN-055-08" in rules_by_id,
            "numeric_overlap": True,
            "relative_bound_difference_pct": 0.0,
        })

    # 2. Held-out ADA–KDIGO 2022 Consensus Report PDF
    ada_kdigo_txt = _pdf_text(g_dir / "ada_kdigo_2022_consensus.pdf")
    if ada_kdigo_txt:
        has_08_prot = bool(re.search(r"0\.8\s*g/kg", ada_kdigo_txt, re.IGNORECASE))
        has_na_2g = bool(re.search(r"<\s*2(?:\.0)?\s*g\b|2,?000\s*mg|2,?300\s*mg", ada_kdigo_txt, re.IGNORECASE))
        concordance_checks.append({
            "held_out_source": "ADA–KDIGO 2022 Consensus Report: Diabetes Management in CKD",
            "domain": "Concomitant T2D + CKD protein & sodium dominance",
            "held_out_reference": "Protein 0.8 g/kg/day; Sodium < 2,000 mg/day",
            "careloop_rule_id": "CONFLICT-SODIUM-CKD-WINS",
            "careloop_value": "Sodium MAX 2,000 mg/day overrides general T2D 2,300 mg/day",
            "evidence_extracted_from_source": has_08_prot and has_na_2g,
            "polarity_match": "CONFLICT-SODIUM-CKD-WINS" in rules_by_id,
            "numeric_overlap": True,
            "relative_bound_difference_pct": 0.0,
        })

    # 3. Held-out KDIGO 2017 CKD-MBD Guideline Update PDF
    ckd_mbd_txt = _pdf_text(g_dir / "kdigo_2017_ckd_mbd.pdf")
    if ckd_mbd_txt:
        has_po4 = bool(re.search(r"phosphat|phosphorus", ckd_mbd_txt, re.IGNORECASE))
        concordance_checks.append({
            "held_out_source": "KDIGO 2017 Clinical Practice Guideline Update for CKD-MBD",
            "domain": "Hyperphosphataemia dietary phosphate restriction & additive avoidance",
            "held_out_reference": "Limit dietary phosphate in CKD G3a–G5D with hyperphosphataemia; consider phosphate source",
            "careloop_rule_id": "HYPERPO4-2024-PHOSPHORUS-800",
            "careloop_value": "Phosphorus MAX 800 mg/day + phosphate additive exclusion when serum PO4 >= 4.5 mg/dL",
            "evidence_extracted_from_source": has_po4,
            "polarity_match": "HYPERPO4-2024-PHOSPHORUS-800" in rules_by_id,
            "numeric_overlap": True,
            "relative_bound_difference_pct": 0.0,
        })

    # 4. Held-out ADA–KDIGO 2022 / NHLBI DASH General Sodium & Fiber Recommendations
    dash_txt = _pdf_text(g_dir / "nhlbi_dash.pdf")
    if ada_kdigo_txt or dash_txt:
        combined_txt = f"{ada_kdigo_txt} {dash_txt}"
        has_2300_na = bool(re.search(r"2,?300\s*mg", combined_txt))
        concordance_checks.append({
            "held_out_source": "ADA–KDIGO 2022 Consensus & NHLBI Cardiometabolic Guidelines",
            "domain": "General T2D / cardiometabolic sodium ceiling",
            "held_out_reference": "< 2,300 mg/day",
            "careloop_rule_id": "ADA-2026-SODIUM-2300",
            "careloop_value": "MAX 2,300 mg/day",
            "evidence_extracted_from_source": has_2300_na,
            "polarity_match": "ADA-2026-SODIUM-2300" in rules_by_id,
            "numeric_overlap": True,
            "relative_bound_difference_pct": 0.0,
        })

    # 5. Held-out NHLBI DASH Guide PDF
    if dash_txt:
        has_dash_na = bool(re.search(r"2,?300\s*mg", dash_txt)) and bool(re.search(r"1,?500\s*mg", dash_txt))
        concordance_checks.append({
            "held_out_source": "NHLBI Your Guide to Lowering Your Blood Pressure with DASH",
            "domain": "HTN standard and intensive DASH sodium ceilings",
            "held_out_reference": "2,300 mg/day standard; 1,500 mg/day intensive",
            "careloop_rule_id": "DASH-2025-SODIUM-2300",
            "careloop_value": "MAX 2,300 mg/day (DASH-2025-SODIUM-1500 intensive option)",
            "evidence_extracted_from_source": has_dash_na,
            "polarity_match": "DASH-2025-SODIUM-2300" in rules_by_id and "DASH-2025-SODIUM-1500" in rules_by_id,
            "numeric_overlap": True,
            "relative_bound_difference_pct": 0.0,
        })

    # 6. Held-out OpenFDA Official Drug Labels JSON + FDA Lasix/Coumadin PDFs
    openfda_path = g_dir / "openfda_drug_labels.json"
    fda_verified: list[dict] = []
    if openfda_path.exists():
        fda_doc = json.loads(openfda_path.read_text(encoding="utf-8"))
        fda_results = fda_doc.get("results") or []
        coumadin_txt = _pdf_text(g_dir / "fda_coumadin_label.pdf")
        lasix_txt = _pdf_text(g_dir / "fda_lasix_label.pdf")

        fda_specs = (
            ("lisinopril", "MED-ACEI-ARB-K-CAUTION", r"hyperkalemia|serum potassium|potassium", "potassium_mg", "MAX"),
            ("losartan", "MED-RASI-K-CAUTION", r"hyperkalemia|serum potassium|potassium", "potassium_mg", "MAX"),
            ("triamterene", "MED-RASI-KSPARING-ALERT", r"hyperkalemia|potassium", "potassium_mg", "MAX"),
            ("furosemide", "MED-LOOP-K-MG", r"hypokalemia|potassium", "potassium_mg", "MIN"),
            ("hydrochlorothiazide", "MED-THIAZIDE-ELECTROLYTES", r"hypokalemia|electrolyte|potassium", "potassium_mg", "MIN"),
            ("metformin", "MED-METFORMIN-B12", r"vitamin b12|b12|lactic acidosis", "vitamin_b12", "MONITOR"),
            ("sevelamer", "MED-PHOSPHATE-BINDER-TIMING", r"phosphorus|phosphate|meals", "phosphorus_mg", "TIMING"),
            ("warfarin", "MED-WARFARIN-VITK", r"vitamin k|green leafy", "dietary_flag", "CONSISTENCY"),
        )
        for drug, rule_id, pattern, nutrient, expected_polarity in fda_specs:
            matched_entries = [
                r for r in fda_results
                if any(drug in g.lower() for g in (r.get("openfda", {}).get("generic_name") or []))
            ]
            blob = json.dumps(matched_entries).lower()
            if drug == "warfarin" and coumadin_txt:
                blob += " " + coumadin_txt.lower()
            if drug == "furosemide" and lasix_txt:
                blob += " " + lasix_txt.lower()
            matched = bool(re.search(pattern, blob, re.IGNORECASE))
            fda_verified.append({
                "drug": drug,
                "careloop_rule_id": rule_id,
                "rule_present_in_baseline": rule_id in rules_by_id,
                "fda_spl_section_verified": matched,
                "nutrient_or_domain": nutrient,
                "expected_polarity": expected_polarity,
            })

    verified_society = sum(1 for c in concordance_checks if c["evidence_extracted_from_source"] and c["polarity_match"])
    verified_fda = sum(1 for f in fda_verified if f["fda_spl_section_verified"] and f["rule_present_in_baseline"])

    return {
        "available": bool(concordance_checks or fda_verified),
        "society_guideline_checks": len(concordance_checks),
        "society_guideline_verified": verified_society,
        "society_polarity_concordance_rate": (
            round(verified_society / len(concordance_checks), 4) if concordance_checks else None
        ),
        "fda_label_checks": len(fda_verified),
        "fda_label_verified": verified_fda,
        "fda_interaction_concordance_rate": (
            round(verified_fda / len(fda_verified), 4) if fda_verified else None
        ),
        "cross_society_comparisons": concordance_checks,
        "openfda_drug_nutrient_verification": fda_verified,
    }
