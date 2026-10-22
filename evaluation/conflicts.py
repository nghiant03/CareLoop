from __future__ import annotations

from collections.abc import Callable
from typing import Any

from evaluation.common import (
    fired_rule_ids,
    has_target,
    is_superseded,
    target_value,
)
from rules.engine import run_rules

__all__ = ["conflict_cases", "evaluate_conflicts"]

Check = Callable[[dict[str, Any], list[dict[str, Any]]], bool]


def _fixture(patient_id: str, weight: float, diagnoses: list[str], *,
             egfr: float | None = None, k: float | None = None, po4: float | None = None,
             meds: list[str] | None = None, bmi: float = 26.0, pregnant: bool = False,
             age: int = 60, sex: str = "F") -> dict[str, Any]:
    return {
        "patient_id": patient_id,
        "age": age,
        "sex": sex,
        "weight_kg": weight,
        "diagnoses": diagnoses,
        "egfr": egfr if egfr is not None else -1,
        "serum_K_meq_L": k if k is not None else -1,
        "serum_PO4_mg_dL": po4 if po4 is not None else -1,
        "meds": meds or [],
        "bmi": bmi,
        "pregnant": pregnant,
    }


def conflict_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "CKD4 + HTN + T2D: sodium max 2000 (KDIGO 90 beats DASH 2300 / ADA 2300)",
            "patient": _fixture("EVAL-C1", 70.0, ["CKD_stage_4", "HTN", "T2D"],
                                egfr=22.0, k=5.4, po4=4.0, meds=["ACEi"]),
            "checks": [
                ("sodium_mg max == 2000 mg",
                 lambda e, t: target_value(e, "sodium_mg", "max") == 2000.0),
                ("DASH-2025-SODIUM-2300 fired and marked SUPERSEDED",
                 lambda e, t: "DASH-2025-SODIUM-2300" in fired_rule_ids(t)
                 and is_superseded(t, "DASH-2025-SODIUM-2300")),
                ("ADA-2026-SODIUM-2300 fired and marked SUPERSEDED",
                 lambda e, t: "ADA-2026-SODIUM-2300" in fired_rule_ids(t)
                 and is_superseded(t, "ADA-2026-SODIUM-2300")),
                ("CONFLICT-SODIUM-CKD-WINS fired (conflict policy applied)",
                 lambda e, t: "CONFLICT-SODIUM-CKD-WINS" in fired_rule_ids(t)),
            ],
        },
        {
            "name": "CKD3 + HTN with normal K (4.3): NO potassium constraint despite DASH",
            "patient": _fixture("EVAL-C2", 65.0, ["CKD_stage_3", "HTN"],
                                egfr=45.0, k=4.3, po4=3.5),
            "checks": [
                ("no potassium_mg target of any kind",
                 lambda e, t: not has_target(e, "potassium_mg", "max")
                 and not has_target(e, "potassium_mg", "min")
                 and not has_target(e, "potassium_mg", "target")),
                ("CONFLICT-K-DASH-NORMAL fired",
                 lambda e, t: "CONFLICT-K-DASH-NORMAL" in fired_rule_ids(t)),
                ("DASH-2025-POTASSIUM-4700 did not fire (CKD gate)",
                 lambda e, t: "DASH-2025-POTASSIUM-4700" not in fired_rule_ids(t)),
            ],
        },
        {
            "name": "CKD4 + hyperkalaemia (K 5.4): potassium max 2400 + high-K foods excluded",
            "patient": _fixture("EVAL-C3", 80.0, ["CKD_stage_4"],
                                egfr=25.0, k=5.4, po4=3.4),
            "checks": [
                ("potassium_mg max == 2400 mg",
                 lambda e, t: target_value(e, "potassium_mg", "max") == 2400.0),
                ("exclusion dish_category 'high_potassium_foods' present (HYPERK-2024-EXCLUDE-HIGH-K)",
                 lambda e, t: any(x["kind"] == "dish_category"
                                  and x["value"] == "high_potassium_foods"
                                  and x["citation"]["rule_id"] == "HYPERK-2024-EXCLUDE-HIGH-K"
                                  for x in e["exclusions"])),
                ("exclusion ingredient 'potassium_chloride' present",
                 lambda e, t: any(x["kind"] == "ingredient"
                                  and x["value"] == "potassium_chloride"
                                  for x in e["exclusions"])),
            ],
        },
        {
            "name": "Severe hyperkalaemia (K 5.6, no HTN): safety rule tightens K max to 2000",
            "patient": _fixture("EVAL-C4", 80.0, ["CKD_stage_4"],
                                egfr=25.0, k=5.6, po4=3.4),
            "checks": [
                ("potassium_mg max == 2000 mg (SAFETY 88 beats HYPERK 85)",
                 lambda e, t: target_value(e, "potassium_mg", "max") == 2000.0),
                ("SAFETY-HYPERK-SEVERE fired",
                 lambda e, t: "SAFETY-HYPERK-SEVERE" in fired_rule_ids(t)),
                ("HYPERK-2024-POTASSIUM-2400 marked SUPERSEDED",
                 lambda e, t: is_superseded(t, "HYPERK-2024-POTASSIUM-2400")),
            ],
        },
        {
            "name": "T2D + CKD4: KDIGO protein 0.55-0.8 g/kg replaces ADA protein targets",
            "patient": _fixture("EVAL-C5", 70.0, ["T2D", "CKD_stage_4"],
                                egfr=28.0, k=4.4, po4=3.6, meds=["metformin"]),
            "checks": [
                ("protein_g max == 0.8 g/kg x 70 kg = 56.0 g",
                 lambda e, t: target_value(e, "protein_g", "max") == 56.0),
                ("protein_g min == 0.55 g/kg x 70 kg = 38.5 g",
                 lambda e, t: target_value(e, "protein_g", "min") == 38.5),
                ("no ADA protein target (1.0 g/kg) present",
                 lambda e, t: not has_target(e, "protein_g", "target")),
                ("ADA-2026-PROTEIN did not fire (CKD not_in gate)",
                 lambda e, t: "ADA-2026-PROTEIN" not in fired_rule_ids(t)),
            ],
        },
        {
            "name": "T2D + HTN: DASH outranks ADA on fibre min (30 vs 25) and sat-fat max "
                    "(13 vs 22); sodium stays 2300",
            "patient": _fixture("EVAL-C6", 68.3, ["T2D", "HTN"],
                                egfr=79.6, k=4.42, po4=3.51, meds=["metformin", "ACEi"]),
            "checks": [
                ("fiber_g min == 30 (DASH p70 beats ADA p25)",
                 lambda e, t: target_value(e, "fiber_g", "min") == 30.0),
                ("ADA-2026-FIBER-25-30 marked SUPERSEDED on fibre min",
                 lambda e, t: is_superseded(t, "ADA-2026-FIBER-25-30")),
                ("sat_fat_g max == 13 (DASH beats ADA 22)",
                 lambda e, t: target_value(e, "sat_fat_g", "max") == 13.0),
                ("sodium_mg max == 2300 (no CKD, so DASH ceiling applies)",
                 lambda e, t: target_value(e, "sodium_mg", "max") == 2300.0),
                ("DASH potassium target 4700 + min 3500 kept (no CKD, K normal)",
                 lambda e, t: target_value(e, "potassium_mg", "target") == 4700.0
                 and target_value(e, "potassium_mg", "min") == 3500.0),
            ],
        },
        {
            "name": "HTN alone with normal K: DASH potassium target 4700 + min 3500 kept",
            "patient": _fixture("EVAL-C7", 65.0, ["HTN"], egfr=76.2, k=4.28, po4=4.06,
                                meds=["ACEi"]),
            "checks": [
                ("potassium_mg target == 4700",
                 lambda e, t: target_value(e, "potassium_mg", "target") == 4700.0),
                ("potassium_mg min == 3500",
                 lambda e, t: target_value(e, "potassium_mg", "min") == 3500.0),
                ("no potassium_mg max",
                 lambda e, t: not has_target(e, "potassium_mg", "max")),
            ],
        },
        {
            "name": "Salience tie: two prio-90 sodium rules with the same value merge "
                    "into a single target (no supersede between them)",
            "patient": _fixture("EVAL-C8", 70.0, ["CKD_stage_4", "HTN", "T2D"],
                                egfr=22.0, k=5.4, po4=4.0),
            "checks": [
                ("exactly one sodium_mg max target",
                 lambda e, t: len([x for x in e["targets"]
                                   if x["nutrient"] == "sodium_mg" and x["kind"] == "max"]) == 1),
                ("both CKD-2024-SODIUM-2000 and CONFLICT-SODIUM-CKD-WINS fired",
                 lambda e, t: {"CKD-2024-SODIUM-2000", "CONFLICT-SODIUM-CKD-WINS"}
                 <= fired_rule_ids(t)),
                ("neither prio-90 sodium rule marked SUPERSEDED (same-value merge)",
                 lambda e, t: not is_superseded(t, "CKD-2024-SODIUM-2000")
                 and not is_superseded(t, "CONFLICT-SODIUM-CKD-WINS")),
            ],
        },
        {
            "name": "Pregnancy: REJECTED envelope, no nutrient targets, scope rule cited",
            "patient": _fixture("EVAL-C9", 64.3, ["pregnancy", "T2D"],
                                egfr=84.7, k=3.91, po4=3.63, meds=["insulin"],
                                pregnant=True, age=34),
            "checks": [
                ("envelope status == REJECTED",
                 lambda e, t: e["status"] == "REJECTED"),
                ("no nutrient targets",
                 lambda e, t: len(e["targets"]) == 0),
                ("SCOPE-PREGNANCY-EXCLUDE fired with a complete citation",
                 lambda e, t: "SCOPE-PREGNANCY-EXCLUDE" in fired_rule_ids(t)
                 and all(row["citation"]["guideline"] and row["citation"]["section"]
                         for row in t if row["rule_id"] == "SCOPE-PREGNANCY-EXCLUDE")),
                ("notes disclose careloop_eligible=false",
                 lambda e, t: "careloop_eligible=false" in (e.get("notes") or "")),
            ],
        },
        {
            "name": "Healthy adult: generic envelope only (GEN rules, no disease rules)",
            "patient": _fixture("EVAL-C10", 71.6, [], egfr=104.4, k=3.86, po4=3.14,
                                age=27, sex="M"),
            "checks": [
                ("sodium_mg max == 2300 (GEN-SODIUM-2300)",
                 lambda e, t: target_value(e, "sodium_mg", "max") == 2300.0),
                ("protein_g min == 0.8 x 71.6 = 57.28 g",
                 lambda e, t: target_value(e, "protein_g", "min") == 57.28),
                ("fiber_g min == 25",
                 lambda e, t: target_value(e, "fiber_g", "min") == 25.0),
                ("energy 25-35 kcal/kg: 1790-2506 kcal",
                 lambda e, t: target_value(e, "energy_kcal", "min") == 1790.0
                 and target_value(e, "energy_kcal", "max") == 2506.0),
                ("status PROPOSED and only generic rules fired",
                 lambda e, t: e["status"] == "PROPOSED"
                 and all(r.startswith("GEN-") for r in fired_rule_ids(t))),
            ],
        },
    ]


def evaluate_conflicts() -> dict[str, Any]:
    cases = []
    total_checks = 0
    passed_checks = 0
    for case in conflict_cases():
        result = run_rules(case["patient"])
        envelope, trace = result["envelope"], result["trace"]
        checks = []
        for expectation, predicate in case["checks"]:
            try:
                ok = bool(predicate(envelope, trace))
            except Exception as exc:  # noqa: BLE001  # a broken predicate must not abort the suite
                ok = False
                expectation += f" [predicate error: {exc}]"
            checks.append({"expectation": expectation, "passed": ok})
            total_checks += 1
            passed_checks += int(ok)
        cases.append({
            "name": case["name"],
            "patient_fixture": case["patient"],
            "engine_status": envelope["status"],
            "engine_targets": envelope["targets"],
            "engine_fired_rules": sorted(fired_rule_ids(trace)),
            "checks": checks,
            "passed": all(c["passed"] for c in checks),
        })
    cases_passed = sum(1 for c in cases if c["passed"])
    return {
        "criterion": "Conflict resolution",
        "definition": (
            "Scripted conflict cases with expected outcomes, checked against the "
            "engine's envelope + trace (priority hierarchy CKD 90 > safety 88 > "
            "hyperkalaemia/med-K 85 > CKD general 80 > DASH 70 > ADA 60 > generic 50; "
            "ties -> stricter value, then rule_id; same-value ties merge)."
        ),
        "cases_total": len(cases),
        "cases_passed": cases_passed,
        "checks_total": total_checks,
        "checks_passed": passed_checks,
        "pass_rate": cases_passed / len(cases) if cases else None,
        "cases": cases,
        "verdict": "PASS" if cases_passed == len(cases) else "FAIL",
    }
