"""Clinical rules compiled to CLIPS, then assembled into envelope and trace dicts.

CLIPS chooses fired rules. Python scales per-kg values, resolves conflicts, and
suppresses scope-rejected targets. ``rules/ENGINE.md`` owns priority/tie policy.
``run_rules`` serializes the shared environment and returns canonical schema
dicts without persistence. Import is allowed without clipspy, execution is not.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from backend.knowledge.runtime import selected_release

# CLIPS is required when running rules; keep module import available without it.
try:
    import clips  # type: ignore

    CLIPS_AVAILABLE = True
except Exception:  # noqa: BLE001  # pragma: no cover - only when the venv lacks clipspy
    clips = None  # type: ignore
    CLIPS_AVAILABLE = False

__all__ = ["CLIPS_AVAILABLE", "run_rules"]

from backend.datasets.paths import dataset_path

_RULES_PATH = dataset_path("rules.json")

# Fixed trace/proposal clock for deterministic engine output; storage stamps live proposals.
_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

_MULTISLOT_FIELDS = {"diagnoses", "meds"}
_NUMERIC_FIELDS = {"age", "weight_kg", "bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL", "hba1c_pct"}
# slots where -1.0 means "unknown" — comparisons must fail on unknown labs
_UNKNOWN_GUARDED = {"bmi", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL", "hba1c_pct"}

# Nutrients whose rulebook values are per-kg coefficients and must be scaled
# by patient weight during assembly (documented in ENGINE.md).
_PER_KG_NUTRIENTS = {"energy_kcal", "protein_g"}

_UNITS = {
    "energy_kcal": "kcal",
    "protein_g": "g",
    "sodium_mg": "mg",
    "potassium_mg": "mg",
    "phosphorus_mg": "mg",
    "carbs_g": "g",
    "fat_g": "g",
    "sat_fat_g": "g",
    "fiber_g": "g",
    "sugar_g": "g",
}

_PRIORITY_BASIS = (
    "CKD stage 3-4 (90) > internal safety (88) > hyperkalaemia/hyperphosphataemia/"
    "medication-K (85) > CKD general (80) > DASH/HTN (70) > ADA (60) > generic (50). "
    "Conflicts resolved per (nutrient, kind): higher priority wins; ties -> lower MAX, "
    "higher MIN, lower TARGET, then lowest rule_id. MIN/TARGET are soft aims. "
    "Losing constraints are marked SUPERSEDED in the trace."
)

_PATIENT_PATTERN = (
    "(patient (patient_id ?patient_id) (age ?age) (sex ?sex) (weight_kg ?weight_kg) "
    "(diagnoses $?diagnoses) (egfr ?egfr) (serum_K_meq_L ?serum_K_meq_L) "
    "(serum_PO4_mg_dL ?serum_PO4_mg_dL) (meds $?meds) (bmi ?bmi) (pregnant ?pregnant) "
    "(hba1c_pct ?hba1c_pct))"
)

_TEMPLATES = [
    """(deftemplate patient
   (slot patient_id (type STRING))
   (slot age (type INTEGER))
   (slot sex (type SYMBOL))
   (slot weight_kg (type FLOAT))
   (multislot diagnoses (type SYMBOL))
   (slot egfr (type FLOAT) (default -1.0))
   (slot serum_K_meq_L (type FLOAT) (default -1.0))
   (slot serum_PO4_mg_dL (type FLOAT) (default -1.0))
   (multislot meds (type SYMBOL))
   (slot bmi (type FLOAT) (default -1.0))
   (slot pregnant (type SYMBOL) (default no))
   (slot hba1c_pct (type FLOAT) (default -1.0)))""",
    ("(deftemplate constraint "
    "(slot nutrient (type SYMBOL)) (slot kind (type SYMBOL)) (slot value (type FLOAT)) "
    "(slot rule_id (type STRING)) (slot priority (type INTEGER)))"),
    ("(deftemplate exclusion "
    "(slot kind (type SYMBOL)) (slot value (type STRING)) (slot reason (type STRING)) "
    "(slot rule_id (type STRING)) (slot priority (type INTEGER)))"),
    ("(deftemplate clinical-flag "
    "(slot key (type SYMBOL)) (slot value (type STRING)) "
    "(slot rule_id (type STRING)) (slot priority (type INTEGER)))"),
    "(deftemplate fired (slot rule_id (type STRING)))",
]



def _sym(value: Any) -> str:
    """Render a value as a CLIPS-safe symbol token."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(value).strip().replace(" ", "_"))


def _esc(text: Any) -> str:
    """Escape a Python string for embedding in a CLIPS quoted string."""
    return str(text).replace("\\", "\\\\").replace('"', "'")


def _fmt(value: Any) -> str:
    return repr(float(value))


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _num(value: Any) -> float:
    """Coerce a lab/vital to float; unknown/NaN -> -1.0 sentinel."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return -1.0
    return -1.0 if math.isnan(f) else f  # NaN -> unknown


def _ruleset() -> list[dict]:
    global _RULESET
    release = selected_release()
    if _RULESET is None:
        if release is not None:
            _RULESET = release.rules_document()["rules"]
        else:
            with open(_RULES_PATH, "r", encoding="utf-8") as fh:
                _RULESET = json.load(fh)["rules"]
    return _RULESET



def _condition_to_clips(cond: dict) -> str:
    field, op, value = cond["field"], cond["op"], cond["value"]

    if field in _MULTISLOT_FIELDS:
        var = f"?{field}"
        syms = [_sym(v) for v in value]
        if op == "in":
            tests = [f"(neq FALSE (member$ {s} {var}))" for s in syms]
            joined = tests[0] if len(tests) == 1 else "(or " + " ".join(tests) + ")"
        elif op == "not_in":
            tests = [f"(eq FALSE (member$ {s} {var}))" for s in syms]
            joined = tests[0] if len(tests) == 1 else "(and " + " ".join(tests) + ")"
        else:
            raise ValueError(f"unsupported op {op!r} for multislot field {field!r}")
        return f"(test {joined})"

    if field == "pregnant":
        if op != "eq":
            raise ValueError(f"unsupported op {op!r} for field 'pregnant'")
        return f"(test (eq ?pregnant {'yes' if value else 'no'}))"

    if field in _NUMERIC_FIELDS:
        var = f"?{field}"
        parts: list[str] = []
        if field in _UNKNOWN_GUARDED:
            parts.append(f"(>= {var} 0.0)")  # -1.0 sentinel must not satisfy tests
        if op == "between":
            lo, hi = value
            parts += [f"(>= {var} {_fmt(lo)})", f"(<= {var} {_fmt(hi)})"]
        elif op in {"ge", "gt", "le", "lt", "eq"}:
            cl = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<", "eq": "eq"}[op]
            parts.append(f"({cl} {var} {_fmt(value)})")
        else:
            raise ValueError(f"unsupported op {op!r} for numeric field {field!r}")
        joined = parts[0] if len(parts) == 1 else "(and " + " ".join(parts) + ")"
        return f"(test {joined})"

    raise ValueError(f"unknown condition field {field!r}")


def _actions_to_clips(rule: dict) -> list[str]:
    rid, prio = rule["rule_id"], int(rule["priority"])
    out = [f'(assert (fired (rule_id "{_esc(rid)}")))']
    for act in rule.get("actions", []):
        kind = act["type"]
        if kind == "set_constraint":
            out.append(
                f'(assert (constraint (nutrient {_sym(act["nutrient"])}) '
                f'(kind {_sym(act["kind"])}) (value {_fmt(act["value"])}) '
                f'(rule_id "{_esc(rid)}") (priority {prio})))'
            )
        elif kind == "exclude":
            out.append(
                f'(assert (exclusion (kind {_sym(act["kind"])}) '
                f'(value "{_esc(act["value"])}") (reason "{_esc(act.get("reason", ""))}") '
                f'(rule_id "{_esc(rid)}") (priority {prio})))'
            )
        elif kind in ("assert", "flag"):  # "flag" is a synonym of "assert"
            out.append(
                f'(assert (clinical-flag (key {_sym(act["key"])}) '
                f'(value "{_esc(_stringify(act["value"]))}") '
                f'(rule_id "{_esc(rid)}") (priority {prio})))'
            )
        else:
            raise ValueError(f"rule {rid}: unsupported action type {kind!r}")
    return out


def _rule_to_defrule(rule: dict) -> str:
    conditions = [_PATIENT_PATTERN] + [_condition_to_clips(c) for c in rule.get("conditions", [])]
    return (
        f"(defrule {_sym(rule['rule_id'])} (declare (salience {int(rule['priority'])})) "
        + " ".join(conditions)
        + " => "
        + " ".join(_actions_to_clips(rule))
        + ")"
    )


_ENV: Any = None
_RULESET: list[dict] | None = None


def _get_env() -> Any:
    """Return the shared mutable environment, compiling rules on first use.

    Callers must hold ``_ENV_LOCK``; this helper does not acquire it.
    ``run_rules`` serializes initialization, execution, and cleanup under that
    lock. Raise RuntimeError when clipspy is unavailable or a rule fails to compile.
    """
    global _ENV
    if _ENV is None:
        if clips is None or not CLIPS_AVAILABLE:
            raise RuntimeError(
                "clipspy is required by rules.engine (pip install clipspy). "
                "rules.clipspy_facts remains import-safe without it."
            )
        env = clips.Environment()
        for template in _TEMPLATES:
            env.build(template)
        for rule in _ruleset():
            try:
                env.build(_rule_to_defrule(rule))
            except Exception as exc:  # surface which rule failed to compile
                raise RuntimeError(f"CLIPS failed to compile rule {rule['rule_id']}: {exc}") from exc
        _ENV = env
    return _ENV



def normalize_patient_labs(patient: dict) -> dict:
    """Copy lab aliases to wire names; an explicit wire name takes precedence.

    Preserve both input spellings. This matches the shared model's alias priority,
    including an explicit null wire value overriding a populated Python spelling.
    """
    normalized = dict(patient)
    for wire, python_name in (("serum_K_meq_L", "serum_k_meq_l"),
                              ("serum_PO4_mg_dL", "serum_po4_mg_dl")):
        if wire not in normalized and python_name in normalized:
            normalized[wire] = normalized[python_name]
    return normalized


def _prepare(patient: dict) -> dict:
    """Normalize for CLIPS; reject missing, nonfinite or nonpositive weight."""
    patient = normalize_patient_labs(patient)
    try:
        weight = float(patient.get("weight_kg", 0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("weight_kg must be finite and positive") from exc
    if not math.isfinite(weight) or weight <= 0:
        raise ValueError("weight_kg must be finite and positive")
    diagnoses = [str(d) for d in (patient.get("diagnoses") or [])]
    age = patient.get("age")
    return {
        "patient_id": str(patient.get("patient_id") or "UNKNOWN"),
        "age": int(age) if age is not None else 0,
        "sex": patient.get("sex") if patient.get("sex") in ("F", "M", "X") else "X",
        "weight_kg": weight,
        "diagnoses": diagnoses,
        "egfr": _num(patient.get("egfr")),
        "serum_K_meq_L": _num(patient.get("serum_K_meq_L")),
        "serum_PO4_mg_dL": _num(patient.get("serum_PO4_mg_dL")),
        "meds": [str(m) for m in (patient.get("meds") or [])],
        "bmi": _num(patient.get("bmi")),
        # The rulebook keys the pregnancy scope gate on ``pregnant``; the data
        # layer also encodes pregnancy as a diagnosis — accept both.
        "pregnant": bool(patient.get("pregnant")) or ("pregnancy" in diagnoses),
        "hba1c_pct": _num(patient.get("hba1c_pct")),
    }


def _patient_fact(p: dict) -> str:
    dx = " ".join(_sym(d) for d in p["diagnoses"])
    meds = " ".join(_sym(m) for m in p["meds"])
    return (
        "(patient "
        f'(patient_id "{_esc(p["patient_id"])}") '
        f"(age {int(p['age'])}) "
        f"(sex {_sym(p['sex'])}) "
        f"(weight_kg {float(p['weight_kg'])}) "
        + (f"(diagnoses {dx}) " if dx else "(diagnoses) ")
        + f"(egfr {p['egfr']}) "
        f"(serum_K_meq_L {p['serum_K_meq_L']}) "
        f"(serum_PO4_mg_dL {p['serum_PO4_mg_dL']}) "
        + (f"(meds {meds}) " if meds else "(meds) ")
        + f"(bmi {p['bmi']}) "
        f"(pregnant {'yes' if p['pregnant'] else 'no'}) "
        f"(hba1c_pct {p['hba1c_pct']}))"
    )



def _harvest(env: Any) -> tuple[list[dict], list[dict], list[dict], set[str]]:
    constraints: list[dict] = []
    exclusions: list[dict] = []
    flags: list[dict] = []
    fired: set[str] = set()
    for fact in env.facts():
        tpl = fact.template.name
        if tpl == "constraint":
            constraints.append(
                {
                    "nutrient": fact["nutrient"],
                    "kind": fact["kind"],
                    "value": float(fact["value"]),
                    "rule_id": fact["rule_id"],
                    "priority": int(fact["priority"]),
                }
            )
        elif tpl == "exclusion":
            exclusions.append(
                {
                    "kind": fact["kind"],
                    "value": fact["value"],
                    "reason": fact["reason"],
                    "rule_id": fact["rule_id"],
                    "priority": int(fact["priority"]),
                }
            )
        elif tpl == "clinical-flag":
            flags.append(
                {
                    "key": fact["key"],
                    "value": fact["value"],
                    "rule_id": fact["rule_id"],
                    "priority": int(fact["priority"]),
                }
            )
        elif tpl == "fired":
            fired.add(fact["rule_id"])
    return constraints, exclusions, flags, fired



def _scale(nutrient: str, value: float, weight_kg: float) -> float:
    if nutrient in _PER_KG_NUTRIENTS and weight_kg > 0:
        return round(value * weight_kg, 2)
    return value


def _resolve_conflicts(constraints: list[dict]) -> tuple[dict, dict[str, list[str]]]:
    """Pick one winner per (nutrient, kind); record losing rules for the trace.

    Highest priority wins. Equal-priority MAX uses the lower ceiling, MIN the
    higher soft floor, and TARGET the lower soft aim. Lowest rule ID breaks any
    remaining tie. TARGET ordering is deterministic, not a stricter hard bound.
    Identical values are merges and are not marked superseded.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in constraints:
        groups.setdefault((c["nutrient"], c["kind"]), []).append(c)

    winners: dict[tuple[str, str], dict] = {}
    losses: dict[str, list[str]] = {}
    for key, cands in groups.items():
        nutrient, kind = key

        def sort_key(c: dict, kind: str = kind) -> tuple:
            strict = -c["value"] if kind == "min" else c["value"]
            return (-c["priority"], strict, c["rule_id"])

        cands.sort(key=sort_key)
        win = cands[0]
        winners[key] = win
        for loser in cands[1:]:
            if loser["rule_id"] == win["rule_id"]:
                continue
            if (loser["nutrient"], loser["kind"], loser["value"]) == (win["nutrient"], win["kind"], win["value"]):
                continue  # same value from another rule: merge, not override
            losses.setdefault(loser["rule_id"], []).append(
                f"superseded by {win['rule_id']} on {nutrient} {kind} "
                f"(final value {win['value']:g} {_UNITS[nutrient]})"
            )
    return winners, losses


def _citation(rule: dict) -> dict:
    return {
        "guideline": rule.get("guideline"),
        "section": rule.get("section"),
        "rule_id": rule["rule_id"],
        "url": rule.get("url"),
        "verbatim_quote": rule.get("verbatim_quote"),
    }


def _cond_summary(cond: dict, prep: dict) -> str:
    field, op, value = cond["field"], cond["op"], cond["value"]
    if field in _MULTISLOT_FIELDS:
        if op == "in":
            matched = [v for v in value if v in set(prep[field])]
            return f"{field} includes {'/'.join(matched) if matched else '...'}"
        return f"{field} excludes {'/'.join(str(v) for v in value)}"
    if field == "pregnant":
        return "pregnant"
    if op == "between":
        return f"{field} in [{value[0]:g}, {value[1]:g}]"
    symbol = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<", "eq": "=="}.get(op, op)
    return f"{field} {symbol} {value:g}" if isinstance(value, (int, float)) else f"{field} {symbol} {value}"


def _patient_summary(rule: dict, prep: dict) -> str:
    conds = rule.get("conditions") or []
    parts = [_cond_summary(c, prep) for c in conds]
    base = " & ".join(parts) if parts else "unconditional (generic adult reference)"
    if any(a.get("type") == "set_constraint" and a.get("nutrient") in _PER_KG_NUTRIENTS for a in rule["actions"]):
        base += f" & weight {prep['weight_kg']:g} kg"
    return base


def _action_summary(rule: dict, prep: dict) -> str:
    weight = prep["weight_kg"]
    pieces: list[str] = []
    for act in rule.get("actions", []):
        action_type = act["type"]
        if action_type == "set_constraint":
            nutrient, constraint_kind, value = act["nutrient"], act["kind"], float(act["value"])
            if nutrient in _PER_KG_NUTRIENTS:
                per = "kcal/kg/d" if nutrient == "energy_kcal" else "g/kg/d"
                if weight > 0:
                    pieces.append(
                        f"set {nutrient} {constraint_kind} = {value:g} {per} -> "
                        f"{round(value * weight, 2):g} {_UNITS[nutrient]}/d (weight {weight:g} kg)"
                    )
                else:
                    # Keep the per-kg marker so unscaled coefficients cannot read as daily doses.
                    pieces.append(
                        f"set {nutrient} {constraint_kind} = {value:g} {per} "
                        f"(weight unknown; not scaled)"
                    )
            else:
                pieces.append(f"set {nutrient} {constraint_kind} = {value:g} {_UNITS[nutrient]}/d")
        elif action_type == "exclude":
            pieces.append(f"exclude {act['kind']} '{act['value']}'")
        else:  # assert / flag
            pieces.append(f"assert {act['key']}={_stringify(act['value'])}")
    return "; ".join(pieces)


_ENV_LOCK = RLock()


def validate_rulebook(rules: list[dict]) -> None:
    """Compile an isolated candidate and check representative scope/suppression cases.

    Does not change the live environment or establish clinical correctness. Call
    after structural DSL validation; this guards publication against removing
    existing scope exclusions, not every possible patient/rule interaction.
    """
    if clips is None or not CLIPS_AVAILABLE:
        raise RuntimeError("clipspy is required to validate knowledge publication")
    candidate = clips.Environment()
    try:
        for template in _TEMPLATES:
            candidate.build(template)
        for rule in rules:
            candidate.build(_rule_to_defrule(rule))
        base = {"patient_id": "KNOWLEDGE-VALIDATION", "age": 60, "sex": "M", "weight_kg": 70,
                "diagnoses": ["T2D", "HTN", "CKD_stage_4"], "egfr": 22,
                "serum_K_meq_L": 5.4, "serum_PO4_mg_dL": 4.0, "hba1c_pct": 7.0}
        cases = [("pregnancy", {"pregnant": True}), ("pregnancy diagnosis", {"diagnoses": ["pregnancy", "T2D"]}),
                 ("paediatric", {"age": 17}), ("dialysis", {"diagnoses": ["dialysis"]}),
                 ("CKD stage 5", {"diagnoses": ["CKD_stage_5"]}), ("eGFR below 15", {"egfr": 14.9}),
                 ("ketoacid-risk", {"hba1c_pct": 10.0})]
        for label, overrides in cases:
            candidate.reset()
            # Return a symbol, not a retained Python Fact wrapper tied to this temporary environment.
            candidate.eval(f"(progn (assert {_patient_fact(_prepare({**base, **overrides}))}) TRUE)")
            candidate.run()
            blocked = candidate.eval(
                '(any-factp ((?flag clinical-flag)) '
                '(or (and (eq ?flag:key careloop_eligible) (eq ?flag:value "false")) '
                '(and (eq ?flag:key auto_envelope_suppressed) (eq ?flag:value "true"))))'
            )
            if str(blocked) != "TRUE":
                raise ValueError(f"candidate rulebook failed scope/suppression check: {label}")
    finally:
        candidate.reset()
        candidate.clear()


def run_rules(patient: dict) -> dict:
    """Return a PROPOSED or scope-rejected envelope and its complete firing trace.

    Returns ``{"envelope": <NutrientEnvelope-compatible dict>,
               "trace": [<RuleFire-compatible dicts>]}``.
    The placeholder envelope ID/time are replaced when stored as a live proposal.
    Access to the shared CLIPS environment is serialized here, including lazy
    initialization and cleanup after failures. Weight must be finite and positive
    or ValueError is raised before execution. No state is persisted or approved.
    """
    ruleset = _ruleset()
    by_id = {r["rule_id"]: r for r in ruleset}
    prep = _prepare(patient)

    with _ENV_LOCK:
        env = _get_env()
        env.reset()
        try:
            env.assert_string(_patient_fact(prep))
            env.run()
            constraints, exclusions, flags, fired_ids = _harvest(env)
        finally:
            env.reset()

    # Record missing scope labs as cautions, without fabricating a fired exclusion.
    for rule in ruleset:
        rid = rule["rule_id"]
        if not rid.startswith("SCOPE-") or rid in fired_ids:
            continue
        for cond in rule.get("conditions", []):
            if cond.get("field") in _UNKNOWN_GUARDED and prep[cond["field"]] < 0:
                flags.append(
                    {
                        "key": "scope_lab_unknown",
                        "value": f"{rid}:{cond['field']}",
                        "rule_id": rid,
                        "priority": int(rule["priority"]),
                    }
                )

    winners, losses = _resolve_conflicts(constraints)

    weight = prep["weight_kg"]
    targets = [
        {
            "nutrient": nutrient,
            "kind": kind,
            "value": _scale(nutrient, c["value"], weight),
            "unit": _UNITS[nutrient],
        }
        for (nutrient, kind), c in sorted(winners.items())
    ]

    # Deduplicate exclusions by kind/value, preferring higher priority.
    def _excl_better(a: dict, b: dict) -> bool:
        if a["priority"] != b["priority"]:
            return a["priority"] > b["priority"]
        return a["rule_id"] < b["rule_id"]

    best_exclusions: dict[tuple[str, str], dict] = {}
    for e in exclusions:
        key = (e["kind"], e["value"])
        cur = best_exclusions.get(key)
        if cur is None or _excl_better(e, cur):
            best_exclusions[key] = e
    exclusions_out = [
        {
            "kind": e["kind"],
            "value": e["value"],
            "reason": e["reason"],
            "citation": _citation(by_id[e["rule_id"]]),
        }
        for _, e in sorted(best_exclusions.items())
    ]

    flags_sorted = sorted(flags, key=lambda f: (f["key"], f["value"], f["rule_id"]))
    out_of_scope_rules = sorted(
        {f["rule_id"] for f in flags if f["key"] == "careloop_eligible" and f["value"] == "false"}
    )
    suppressed_rules = sorted(
        {f["rule_id"] for f in flags if f["key"] == "auto_envelope_suppressed" and f["value"] == "true"}
    )
    out_of_scope = bool(out_of_scope_rules)
    suppressed = bool(suppressed_rules)
    status = "REJECTED" if (out_of_scope or suppressed) else "PROPOSED"
    if status == "REJECTED":
        targets = []  # no auto envelope for out-of-scope / clinician-review cases

    trace: list[dict[str, Any]] = []
    for rid in sorted(fired_ids, key=lambda r: (-by_id[r]["priority"], r)):
        rule = by_id[rid]
        summary = _action_summary(rule, prep)
        marker = losses.get(rid)
        if marker:
            summary += " | SUPERSEDED: " + " | ".join(marker)
        trace.append(
            {
                "rule_id": rid,
                "fired_at": _CLOCK.isoformat(),
                "patient_summary": _patient_summary(rule, prep),
                "action_summary": summary,
                "priority": int(rule["priority"]),
                "citation": _citation(rule),
            }
        )

    citations: list[dict] = []
    seen: set[str] = set()
    for row in trace:
        if row["rule_id"] not in seen:
            seen.add(row["rule_id"])
            citations.append(row["citation"])

    notes_parts: list[str] = []
    if out_of_scope:
        notes_parts.append(
            "OUT OF SCOPE: careloop_eligible=false asserted by "
            + ", ".join(out_of_scope_rules)
            + "; nutrient targets suppressed."
        )
    if suppressed:
        notes_parts.append(
            "AUTO ENVELOPE SUPPRESSED: clinician review required before any nutrient "
            "envelope is produced (asserted by " + ", ".join(suppressed_rules) + ")."
        )
    flags_text = "; ".join(f"{f['key']}={f['value']}" for f in flags_sorted)
    if flags_text:
        notes_parts.append("Cautions/asserts: " + flags_text)
    notes_parts.append("PROPOSED only; downstream optimiser must not consume until a clinician approves.")

    snapshot = {
        "snapshot_version": 2,
        "patient_id": prep["patient_id"],
        "age": prep["age"],
        "sex": prep["sex"],
        "weight_kg": prep["weight_kg"],
        "diagnoses": list(prep["diagnoses"]),
        "egfr": prep["egfr"] if prep["egfr"] >= 0 else None,
        "serum_K_meq_L": prep["serum_K_meq_L"] if prep["serum_K_meq_L"] >= 0 else None,
        "serum_PO4_mg_dL": prep["serum_PO4_mg_dL"] if prep["serum_PO4_mg_dL"] >= 0 else None,
        "meds": list(prep["meds"]),
        "bmi": prep["bmi"] if prep["bmi"] >= 0 else None,
        "pregnant": prep["pregnant"],
        "hba1c_pct": prep["hba1c_pct"] if prep["hba1c_pct"] >= 0 else None,
    }

    envelope = {
        "envelope_id": f"ENV-{prep['patient_id']}-001",
        "patient_id": prep["patient_id"],
        "status": status,
        "scope_eligible": not (out_of_scope or suppressed),
        "version": 1,
        "patient_snapshot": snapshot,
        "targets": targets,
        "exclusions": exclusions_out,
        "fired_rules": trace,
        "citations": citations,
        "priority_basis": _PRIORITY_BASIS,
        "proposed_by": "rules-engine",
        "proposed_at": _CLOCK.isoformat(),
        "approved_by": None,
        "approved_at": None,
        "notes": " | ".join(notes_parts),
    }
    release = selected_release()
    if release is not None:
        envelope["knowledge_release_id"] = release.release_id
        envelope["knowledge_source_hashes"] = release.source_hashes()
        envelope["priority_basis"] = (
            f"Published knowledge release {release.release_id}. Higher rule priority wins per nutrient/kind; "
            "ties choose lower MAX, higher MIN, lower TARGET, then lowest rule_id. "
            "MIN/TARGET are soft aims; losing rules retain SUPERSEDED traces."
        )
    return {"envelope": envelope, "trace": trace}


if __name__ == "__main__":  # pragma: no cover - smoke check
    demo = {
        "patient_id": "SYN-0007",
        "age": 62,
        "sex": "M",
        "weight_kg": 70.0,
        "diagnoses": ["CKD_stage_4", "HTN"],
        "egfr": 22.0,
        "serum_K_meq_L": 5.4,
        "serum_PO4_mg_dL": 4.0,
        "meds": ["ACEi", "loop_diuretic"],
        "bmi": 27.5,
        "pregnant": False,
    }
    result = run_rules(demo)
    print("status:", result["envelope"]["status"])
    print("fired:", len(result["trace"]))
    for target in result["envelope"]["targets"]:
        print("  ", target)
