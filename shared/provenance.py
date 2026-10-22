"""Attach exact target provenance with legacy trace matching."""
import re

from shared.envelope_schema import ConstraintProvenance

_SET = re.compile(
    r"set (?P<nutrient>\w+) (?P<kind>\w+) = (?P<value>-?[\d.]+) "
    r"(?P<unit>[\w/]+)(?:\s+->\s+(?P<final>-?[\d.]+))?"
)


def _canonical_summary(summary):
    aliases = {"Na": "sodium_mg", "K": "potassium_mg", "protein": "protein_g",
               "energy": "energy_kcal", "fiber": "fiber_g", "sat fat": "sat_fat_g"}
    bound = re.match(r"^(Na|K|fiber|sat fat) (ceiling|floor|max) = ([\d.]+) (mg|g|kcal)/d", summary)
    if bound:
        nutrient, kind, value, unit = bound.groups()
        return f"set {aliases[nutrient]} {'min' if kind == 'floor' else 'max'} = {value} {unit}"
    band = re.match(r"^(protein|energy) = [\d.]+-[\d.]+ \w+/kg/d -> ([\d.]+)-([\d.]+) (g|kcal)/d", summary)
    if band:
        nutrient, low, high, unit = band.groups()
        return f"set {aliases[nutrient]} min = {low} {unit}; set {aliases[nutrient]} max = {high} {unit}"
    return summary


def citation_for(target: dict, trace: list[dict]):
    """Search edits newest first. Per kilogram actions match their scaled values."""
    edits = [r for r in reversed(trace) if r.get("rule_id") == "CLINICIAN-EDIT"]
    rules = sorted((r for r in trace if r.get("rule_id") != "CLINICIAN-EDIT"),
                   key=lambda r: -r.get("priority", 0))
    for row in edits + rules:
        for match in _SET.finditer(_canonical_summary(row.get("action_summary", ""))):
            if (match["nutrient"] == target["nutrient"] and match["kind"] == target["kind"]
                    and match["unit"].split("/")[0] == target["unit"]
                    and abs(float(match["final"] or match["value"]) - target["value"]) <= 0.005):
                return row.get("citation")
    return None


def attach_provenance(envelope, *, author=None, citation=None):
    """Preserve existing provenance unless an explicit author override replaces it."""
    trace = [row.model_dump(mode="json") for row in envelope.fired_rules]
    for target in envelope.targets:
        if author is None and target.provenance is not None:
            continue
        source = citation or citation_for(target.model_dump(mode="json"), trace)
        if source:
            target.provenance = ConstraintProvenance(
                nutrient=target.nutrient, kind=target.kind, value=target.value, unit=target.unit,
                envelope_id=envelope.envelope_id, version=envelope.version,
                author=author or "rules-engine", citation=source,
            )
