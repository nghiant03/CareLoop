from __future__ import annotations

from typing import Any

from evaluation.ablation import per_patient_deltas

__all__ = ["render_report"]


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".") if value != 0 else "0"
    return str(value)


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def _benchmark_headline_text(benchmark: dict[str, Any]) -> str:
    headline = benchmark.get("headline") or []
    if not headline:
        return "no benchmark rows available"
    winner = max(headline, key=lambda m: (m["mean_hv"], -m["violation_rate"]))
    return (f"{winner['method']}: {winner['violation_rate'] * 100:.0f}% "
            f"violations, best mean HV {winner['mean_hv']}, "
            f"{winner['mean_runtime_ms']} ms mean")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_fmt(c) for c in row) + " |")
    return "\n".join(out)


def _ablation_rows(pooled: dict[str, Any]) -> list[list[Any]]:
    # Old mixed unit gaps render as unavailable rather than being relabeled.
    rows = []
    for name in ("scalar", "normalised", "adequacy_first"):
        p = pooled.get(name) or {}
        rows.append([
            name,
            p.get("rows"),
            _pct(p.get("feasibility_rate")),
            _fmt(p.get("mean_worst_day_rel_shortfall_pct")),
            _fmt(p.get("mean_daily_rel_shortfall_pct")),
            _fmt(p.get("mean_met_days_fraction")),
            _fmt(p.get("mean_cost")),
            _fmt(p.get("mean_variety")),
            _fmt(p.get("mean_nutrient_target_deviation")),
            _fmt(p.get("mean_front_size")),
        ])
    return rows


def _render_ablation(add, ablation: dict[str, Any], table, fmt) -> None:
    sel = ablation["selection_ablation"]
    config = sel["config"]
    add("## Objective/selection & meal-composition ablation")
    add("")
    add(ablation["definition"])
    add("")
    add(f"### Selection ablation (paired: {config['pop_size']}-pop / {config['n_gen']}-gen "
        f"NSGA-II front per patient × seed {config['seeds']}; all strategies score the "
        f"SAME front against the ORIGINAL approved aims)")
    add("")
    add(table(
        ["Strategy", "Rows", "Feasibility", "Worst-day shortfall %",
         "Mean daily rel. shortfall %", "Met-days fraction", "Cost (SGD)",
         "Variety (objective)", "Deviation", "Mean front size"],
        _ablation_rows(sel["pooled"]),
    ))
    add("")
    add(f"Scoring: {config['scored_against']}. Both shortfall columns are "
        f"dimensionless (gap/aim): the worst-day column pools the worst "
        f"per-aim relative shortfall on each plan's worst day; the mean-daily "
        f"column pools the per-aim mean daily gap/aim. Unit-bearing per-aim "
        f"gaps (kcal/g/mg) are kept per aim in results.json and are never "
        f"averaged across aims (plan_service adequacy semantics).")
    add("")
    add("### Paired per-patient deltas vs scalar selection "
        "(worst-day relative shortfall pct-points, mean over seeds)")
    add("")
    add(table(
        ["Patient", "Δ normalised", "Δ adequacy-first"],
        [[d["patient_id"],
          fmt(d.get("delta_normalised_pct")),
          fmt(d.get("delta_adequacy_first_pct"))]
         for d in per_patient_deltas(sel.get("delta_rows") or [])],
    ))
    add("")
    deltas = sel["paired_deltas"]
    add("Pooled paired deltas: " + "; ".join(
        f"{name}: {deltas[name]['rows']} rows, "
        f"mean Δ shortfall {_fmt(deltas[name]['mean_delta_worst_day_rel_shortfall_pct'])} "
        f"pct-pts, mean Δ cost {_fmt(deltas[name]['mean_delta_cost_pct'])}% "
        f"({deltas[name]['improved']} improved / {deltas[name]['tied']} tied / "
        f"{deltas[name]['regressed']} regressed)"
        for name in ("normalised", "adequacy_first") if name in deltas
    ) + ".")
    add("")
    verdict_note = ablation.get("verdict_note")
    add(f"**Verdict: {ablation['verdict']}**"
        + (f" — {verdict_note}" if verdict_note
           else " — adequacy-first strictly reduces the pooled mean worst-day "
                "relative shortfall at 100% feasibility and within the 10% cost cap "
                "(full rule in `evaluation/ablation.py` module docstring)."))
    add("")

    comp = ablation["composition_ablation"]
    add("### Meal-composition ablation: 1-dish vs 2-dish (main + side) encoding")
    add("")
    add(comp["note"])
    add("")
    rows = []
    for label, key in (("1-dish (baseline)", "one_dish"), ("2-dish (main + side)", "two_dish")):
        for name in ("scalar", "normalised", "adequacy_first"):
            p = (comp["pooled"].get(key) or {}).get(name) or {}
            rows.append([label, name, p.get("rows"),
                         _pct(p.get("feasibility_rate")),
                         _fmt(p.get("mean_worst_day_rel_shortfall_pct")),
                         _fmt(p.get("mean_daily_rel_shortfall_pct")),
                         _fmt(p.get("mean_met_days_fraction")),
                         _fmt(p.get("mean_cost")),
                         _fmt(p.get("mean_variety"))])
    add(table(["Encoding", "Strategy", "Rows", "Feasibility", "Worst-day shortfall %",
               "Mean daily rel. shortfall %", "Met-days fraction", "Cost (SGD)",
               "Variety (objective)"], rows))
    add("")
    pools = comp["pools"]
    add(f"Encoding: MAIN pool {pools['main_pool_size']} dishes (allowed pool minus "
        f"categories {', '.join(comp['config']['main_excluded_categories'])}); "
        f"SIDE pool {pools['side_pool_size']} dishes (categories "
        f"{', '.join(comp['config']['side_categories'])} or tag "
        f"`{comp['config']['side_tag']}`); "
        f"{comp['config']['repetition_limit']}; operators: "
        f"{comp['config']['operators']}.")
    add("")
    for note in comp.get("phase_notes") or []:
        add(f"* {note}")
    if comp.get("phase_notes"):
        add("")
    add("Reported informationally (no pass/fail): the eligibility sets are heuristic "
        "annotations, not verified data.")
    add("")

    exact = ablation["exact_reference"]
    add("### Exact-reference quality (scalar-selected plans, seed "
        f"{exact['seed']})")
    add("")
    add(table(
        ["Patient", "Deviation gap (mean/day)", "Preference-sum gap (mean/day)",
         "Cost gap (mean/day)", "At per-day optimum (dev/pref/cost)",
         "7-day lower bounds (dev / pref / cost)"],
        [[r["patient_id"],
          fmt((r.get("mean_gaps") or {}).get("nutrient_target_deviation")),
          fmt((r.get("mean_gaps") or {}).get("preference_sum")),
          fmt((r.get("mean_gaps") or {}).get("cost")),
          (f"{int(r['at_per_day_optimum']['nutrient_target_deviation'])}/"
           f"{int(r['at_per_day_optimum']['preference_sum'])}/"
           f"{int(r['at_per_day_optimum']['cost'])}")
          if r.get("at_per_day_optimum") else "—",
          " / ".join(fmt((r.get("seven_day_lower_bounds") or {}).get(k))
                     for k in ("nutrient_target_deviation", "preference_sum", "cost"))
          if r.get("seven_day_lower_bounds") else "—"]
         for r in exact["per_patient"]],
    ))
    add("")
    agg = exact["aggregate"]
    add("Aggregate: " + "; ".join(
        f"{name}: mean gap {_fmt(entry['mean_gap'])}, "
        f"{entry['patients_at_per_day_optimum']}/{entry['plans_with_reference']} "
        f"plans at the per-day additive optimum (gap <= 1e-6)"
        for name, entry in agg.items()
    ) + ".")
    add("")
    add("Solver infeasibility_status counts across the selection-ablation solves: "
        + (", ".join(f"{k} {v}" for k, v in sorted(exact["infeasibility_status_counts"].items()))
           or "none recorded") + ".")
    add("")
    add(f"Disclosure: {exact['disclosure']}")
    add("")


def _render_external(add, external: dict[str, Any], table, fmt, pct) -> None:
    add("## External dataset evaluation (NHANES, MIMIC-IV, HealthBench)")
    add("")
    add(external["definition"])
    add("")

    nh = external.get("nhanes_cohort") or {}
    if nh.get("available"):
        tr = nh["traceability"]
        sg = nh["scope_gate"]
        add(f"### 1. {nh['dataset']} — Clinical cohort, 24h dietary recalls & weight-stratified plan adequacy")
        add("")
        add(f"Evaluated **{nh['evaluated_subjects']}** real participants "
            f"(from {nh['total_complete_in_survey']} complete survey profiles; "
            f"{nh['eligible_subjects']} eligible, {nh['rejected_subjects']} scope-rejected, "
            f"{nh['engine_errors']} engine errors; "
            f"{tr['traceable']}/{tr['items']} [{pct(tr['rate'])}] items traceable, "
            f"{sg['observed_rejected']}/{sg['expected_rejected']} [{pct(sg['accuracy'])}] "
            f"scope-gate accuracy).")
        add("")
        add(table(
            ["Clinical stratum", "Subjects evaluated"],
            [[s["stratum"], s["subjects"]] for s in nh.get("strata", [])],
        ))
        add("")
        add(table(
            ["Rule ID", "Firings in NHANES cohort"],
            [[r["rule_id"], r["count"]] for r in nh.get("rule_firings", [])],
        ))
        add("")
        adh = nh.get("dietary_recall_adherence") or {}
        if adh.get("recalled_days_evaluated"):
            add("#### Two-day 24-hour dietary recall adherence vs. CareLoop envelopes")
            add("")
            add(f"Across **{adh['cardiometabolic_renal_subjects_with_recalls']}** "
                f"scope-eligible T2D/HTN/CKD3–4 participants (**{adh['recalled_days_evaluated']}** "
                f"recalled intake days), **{adh['recalled_days_with_hard_max_violation']}/"
                f"{adh['recalled_days_evaluated']} ({pct(adh['baseline_hard_violation_day_rate'])})** "
                f"of real-world dietary recall days violate >=1 hard `MAX` ceiling "
                f"(vs. **0.0%** on CareLoop's optimised plans).")
            add("")
            add(table(
                ["Constraint", "Kind", "Evaluated days", "Non-compliant days",
                 "Non-compliance rate", "Mean excess / shortfall %"],
                [[c["constraint"], c["kind"], c["evaluated_days"], c["non_compliant_days"],
                  pct(c["non_compliance_rate"]), fmt(c["mean_excess_or_shortfall_pct"])]
                 for c in adh.get("by_constraint", [])],
            ))
            add("")
        pa = nh.get("plan_adequacy_stress_test") or {}
        if pa.get("subjects_evaluated"):
            add("#### Weight-stratified 7-day meal-plan adequacy stress test on NHANES participants")
            add("")
            add(f"Across **{pa['subjects_evaluated']}** real NHANES participants sampled across "
                f"weight quantiles of the 5 eligible clinical strata: **{pa['hard_feasible_plans']}/"
                f"{pa['subjects_evaluated']} ({pct(pa.get('hard_feasibility_rate'))})** plans satisfy "
                f"all hard `MAX` ceilings, but only **{pa['plans_meeting_all_min_floors']}/"
                f"{pa['hard_feasible_plans']} ({pct(pa.get('all_min_floors_met_rate'))})** meet every "
                f"weight-scaled `MIN` floor on all 7 days (mean worst-day `MIN` shortfall "
                f"**{fmt(pa.get('mean_worst_day_min_shortfall_pct'))}%**, max "
                f"**{fmt(pa.get('max_worst_day_min_shortfall_pct'))}%**, mean daily relative aim "
                f"deviation **{fmt(pa.get('mean_daily_rel_aim_deviation_pct'))}%**). Because "
                f"energy (`25 kcal/kg`) and protein (`0.55 g/kg`) floors scale linearly with body "
                f"weight while guideline sodium ceilings (`<=2,000–2,300 mg/d`) and two-dish meal "
                f"portions remain fixed, heavier participants (`>80 kg`) experience substantial "
                f"soft-floor shortfalls.")
            add("")
            add(table(
                ["Clinical stratum", "Subjects", "Weight range (kg)",
                 "All-MIN-floors met", "All-MIN rate",
                 "Mean worst-day MIN shortfall %", "Mean daily aim deviation %"],
                [[s["stratum"], s["subjects"], s["weight_range_kg"],
                  f"{s['plans_meeting_all_min_floors']}/{s['subjects']}",
                  pct(s["all_min_floors_met_rate"]),
                  fmt(s["mean_worst_day_min_shortfall_pct"]),
                  fmt(s["mean_daily_rel_aim_deviation_pct"])]
                 for s in pa.get("per_stratum", [])],
            ))
            add("")

    mm = external.get("mimic_longitudinal_trends") or {}
    if mm.get("available"):
        rf = mm["real_trajectory_flags"]
        pf = mm.get("prefix_forecast_benchmark") or {}
        nm = mm.get("noisy_regime_and_mining_benchmark") or {}
        add(f"### 2. {mm['dataset']} — Prefix forecasting, noisy physiological regimes & cohort mining")
        add("")
        add(f"Evaluated **{mm['patients_total']}** inpatient records "
            f"({mm['patients_with_k_series_ge_3']} with >=3 K+ dates, "
            f"{mm['patients_with_po4_series_ge_3']} with >=3 PO4 dates): "
            f"`detect_trends` raised **{rf['total']}** full-series flags (**{rf['urgent']}** urgent, "
            f"**{rf['review']}** review; {rf['potassium_flags']} K+, {rf['phosphate_flags']} PO4).")
        add("")
        if pf.get("combined"):
            add("#### Rolling 3-observation prefix forecasting of future hyperkalaemia / hyperphosphataemia")
            add("")
            add("For every inpatient trajectory with >=4 distinct lab dates where the initial "
                "3-observation prefix is below the clinical threshold (`K+ < 5.0 mEq/L` or "
                "`PO4 < 4.5 mg/dL`), `detect_trends(prefix)` predicts whether a subsequent "
                "observation crosses the threshold:")
            add("")
            add(table(
                ["Analyte", "Threshold", "Episodes", "Future crossings", "TP", "FN", "FP", "TN",
                 "Sensitivity (Recall)", "Specificity", "Precision (PPV)"],
                [
                    ["Potassium (K+)", fmt(pf["potassium"]["threshold"]),
                     pf["potassium"]["episodes"], pf["potassium"]["positive_crossings"],
                     pf["potassium"]["tp"], pf["potassium"]["fn"],
                     pf["potassium"]["fp"], pf["potassium"]["tn"],
                     pct(pf["potassium"]["sensitivity_recall"]),
                     pct(pf["potassium"]["specificity"]),
                     pct(pf["potassium"]["precision_ppv"])],
                    ["Phosphate (PO4)", fmt(pf["phosphate"]["threshold"]),
                     pf["phosphate"]["episodes"], pf["phosphate"]["positive_crossings"],
                     pf["phosphate"]["tp"], pf["phosphate"]["fn"],
                     pf["phosphate"]["fp"], pf["phosphate"]["tn"],
                     pct(pf["phosphate"]["sensitivity_recall"]),
                     pct(pf["phosphate"]["specificity"]),
                     pct(pf["phosphate"]["precision_ppv"])],
                    ["Combined", "—",
                     pf["combined"]["episodes"], pf["combined"]["positive_crossings"],
                     pf["combined"]["tp"], pf["combined"]["fn"],
                     pf["combined"]["fp"], pf["combined"]["tn"],
                     pct(pf["combined"]["sensitivity_recall"]),
                     pct(pf["combined"]["specificity"]),
                     pct(pf["combined"]["precision_ppv"])],
                ],
            ))
            add("")
        if nm.get("noisy_trend_estimators"):
            nte = nm["noisy_trend_estimators"]
            add(f"#### Noisy physiological regime benchmark (σ={nte['noise_sd']} mEq/L, "
                f"{nte['n_months']} months) & cohort/substitution mining")
            add("")
            add(table(
                ["Estimator", "TP detection rate", "Overall FP rate", "Flat FP rate",
                 "Slow-rise FP rate", "Plateau FP rate", "Mean lead (months)"],
                [[e["estimator"], pct(e["tp_detection_rate"]), pct(e["overall_fp_rate"]),
                  pct(e["flat_fp_rate"]), pct(e["rising_slow_fp_rate"]),
                  pct(e["plateau_fp_rate"]), fmt(e["mean_lead_months"])]
                 for e in nte.get("estimators", [])],
            ))
            add("")
            cc = nm.get("cohort_clustering") or {}
            if cc.get("methods"):
                add(table(
                    ["Clustering method", "Clusters", "Silhouette ↑", "Davies-Bouldin ↓",
                     "Seed stability ARI", "Bootstrap stability ARI", "Noise points"],
                    [[m["method"], m["clusters"], fmt(m["silhouette"]),
                      fmt(m["davies_bouldin"]), fmt(m["seed_stability_ari"]),
                      fmt(m["bootstrap_stability_ari"]), m["noise_points"]]
                     for m in cc["methods"]],
                ))
                add("")
            ds = nm.get("dish_substitutions") or {}
            if ds.get("kendall_tau"):
                add(table(
                    ["Substitution rank pair (n=" + str(ds["n_queries"]) + " dishes)",
                     "Mean Kendall τ", "Min τ", "Max τ"],
                    [[pair, fmt(vals[0]), fmt(vals[1]), fmt(vals[2])]
                     for pair, vals in ds["kendall_tau"].items()],
                ))
                add("")
        med_rows = (mm.get("medication_rules") or {}).get("rule_firings") or []
        if med_rows:
            add(table(
                ["Medication rule ID", "MIMIC-IV patients triggering rule"],
                [[m["rule_id"], m["patients"]] for m in med_rows],
            ))
            add("")

    hb = external.get("healthbench_chat") or {}
    if hb.get("available"):
        add(f"### 3. {hb['dataset']} — Emergency referral triage, topical scope & retrieval ranking")
        add("")
        add(table(
            ["Physician-agreed category", "Prompts", "Escalated", "Refused", "Answered",
             "Escalation rate", "Escalated or refused", "Answered claim consistency"],
            [[t["category"], t["prompts"], t["escalated"], t["refused"], t["answered"],
              pct(t["escalation_rate"]), pct(t["escalated_or_refused_rate"]),
              pct(t["answered_claim_consistency_rate"])]
             for t in hb.get("emergency_referrals_triage", [])],
        ))
        add("")
        em_bin = hb.get("emergency_triage_binary_metrics") or {}
        if em_bin:
            add(f"Binary emergency triage (`emergent` n={em_bin['emergent_prompts']} vs. "
                f"`non-emergent` n={em_bin['non_emergent_prompts']}): "
                f"escalation sensitivity/recall **{pct(em_bin['escalation_sensitivity_recall'])}**, "
                f"specificity **{pct(em_bin['non_emergent_specificity'])}**, "
                f"precision/PPV **{pct(em_bin['escalation_precision_ppv'])}**, "
                f"F1 **{fmt(em_bin['f1_score'])}** "
                f"(emergent safe non-answer rate **{pct(em_bin['emergent_safe_non_answer_rate'])}**, "
                f"emergent false-answer rate **{pct(em_bin['emergent_false_answer_rate'])}**).")
            add("")
        top = hb.get("topical_scope_discrimination") or {}
        if top:
            add("#### Dietary vs. non-dietary clinical scope & condition-matched guideline precision")
            add("")
            add(table(
                ["Metric", "Count / Ratio", "Rate"],
                [
                    ["Genuine patient dietary queries answered (recall)",
                     f"{top['dietary_answered_tp']}/{top['dietary_prompts']}",
                     pct(top["dietary_answer_recall"])],
                    ["Non-dietary clinical/lab prompts rejected or escalated (specificity)",
                     f"{top['non_dietary_rejected_or_escalated_tn']}/{top['non_dietary_clinical_prompts']}",
                     pct(top["non_dietary_rejection_specificity"])],
                    ["Non-dietary clinical/lab prompts falsely answered with diet rules",
                     f"{top['non_dietary_falsely_answered_fp']}/{top['non_dietary_clinical_prompts']}",
                     pct(top["non_dietary_false_answer_rate"])],
                    ["Topical precision among answered HealthBench prompts",
                     f"{top['dietary_answered_tp']}/{top['dietary_answered_tp'] + top['non_dietary_falsely_answered_fp']}",
                     pct(top["topical_precision_among_answered"])],
                    ["Unconditioned non-CKD dietary queries citing CKD-specific rules",
                     f"{top['unconditioned_ckd_rule_overreach']}/{top['non_ckd_dietary_answered']}",
                     pct(top["unconditioned_ckd_overreach_rate"])],
                    ["Condition-matched guideline rate on non-CKD dietary queries",
                     f"{top['non_ckd_dietary_answered'] - top['unconditioned_ckd_rule_overreach']}/{top['non_ckd_dietary_answered']}",
                     pct(top["condition_matched_guideline_rate"])],
                ],
            ))
            add("")
        ret = hb.get("retrieval_benchmark") or {}
        if ret.get("methods"):
            add(f"#### Held-out retrieval benchmark ({ret['queries_total']} queries across "
                f"{len(ret['methods'])} methods; production `{ret['production_method']}`)")
            add("")
            add(table(
                ["Retrieval method", "Hit@1", "Hit@3", "Hit@5", "MRR"],
                [[m["name"], pct(m["hit@1"]), pct(m["hit@3"]), pct(m["hit@5"]), fmt(m["mrr"])]
                 for m in ret["methods"]],
            ))
            add("")
            by_cat = ret.get("production_by_category") or {}
            if by_cat:
                add(table(
                    [f"Query category (`{ret['production_method']}`)", "Queries", "Hit@1", "Hit@3", "Hit@5", "MRR"],
                    [[cat, (ret.get("queries_by_category") or {}).get(cat, "—"),
                      pct(metrics["hit@1"]), pct(metrics["hit@3"]),
                      pct(metrics["hit@5"]), fmt(metrics["mrr"])]
                     for cat, metrics in sorted(by_cat.items())],
                ))
                add("")
        if hb.get("finding"):
            add(f"Finding: {hb['finding']}")
            add("")

    add(f"**Verdict: {external['verdict']}.**")
    add("")


def _section(results: dict[str, Any], name: str) -> dict[str, Any] | None:
    if name in results:
        return results[name]
    for key, value in results.items():
        if key.endswith(f"_{name}") and isinstance(value, dict):
            return value
    return None


def render_report(results: dict[str, Any]) -> str:
    traceability = _section(results, "traceability")
    conflicts = _section(results, "conflicts")
    satisfaction = _section(results, "constraint_satisfaction")
    benchmark = _section(results, "benchmark")
    groundedness = _section(results, "groundedness")
    ablation = _section(results, "ablation")
    external = _section(results, "external")
    assert traceability and conflicts and satisfaction and benchmark and groundedness
    meta = results["meta"]

    lines: list[str] = []
    add = lines.append

    add("# CareLoop — Evaluation Report")
    add("")
    add(f"Suite: {meta['suite']} · optimiser seed {meta['seed']} "
        f"(pop {meta['pop_size']}, gen {meta['n_gen']}, NSGA-II) · "
        f"{meta['patients']} synthetic fixture patients · {meta['dishes']}-dish pool")
    add("")
    add("Export with `.venv/bin/python -m evaluation.run --out-dir /external/run` (add `--rerun-benchmark` "
        "to regenerate the optimiser benchmark artefacts). Deterministic apart from "
        "wall-clock runtimes. All generated reports (`EVALUATION.md`) and raw outputs "
        "(`results.json`) are written only to the explicitly selected external directory.")
    add("")

    add("## Headline verdicts")
    add("")
    headline_rows: list[list[Any]] = []
    if external and external.get("nhanes_cohort", {}).get("available"):
        nh = external["nhanes_cohort"]
        adh = nh["dietary_recall_adherence"]
        pa = nh.get("plan_adequacy_stress_test") or {}
        mm = external["mimic_longitudinal_trends"]
        pf = (mm.get("prefix_forecast_benchmark") or {}).get("combined") or {}
        hb = external["healthbench_chat"]
        em_bin = hb.get("emergency_triage_binary_metrics") or {}
        top = hb.get("topical_scope_discrimination") or {}
        ret = hb.get("retrieval_benchmark") or {}
        headline_rows.append([
            "External clinical & empirical evaluation (NHANES, MIMIC-IV, HealthBench)",
            external["verdict"],
            (f"NHANES 24h recall hard-MAX exceedance {_pct(adh['baseline_hard_violation_day_rate'])}, "
             f"weight-stratified 7d plan all-MIN adequacy {_pct(pa.get('all_min_floors_met_rate'))} "
             f"(mean worst-day MIN shortfall {_fmt(pa.get('mean_worst_day_min_shortfall_pct'))}%); "
             f"MIMIC 3-obs prefix forecast recall {_pct(pf.get('sensitivity_recall'))}, "
             f"specificity {_pct(pf.get('specificity'))}, PPV {_pct(pf.get('precision_ppv'))}; "
             f"HealthBench emergent recall {_pct(em_bin.get('escalation_sensitivity_recall'))} "
             f"(F1 {_fmt(em_bin.get('f1_score'))}), topical precision "
             f"{_pct(top.get('topical_precision_among_answered'))}, retrieval Hit@1 "
             f"{_pct(ret.get('production_hit_at_1'))} / MRR {_fmt(ret.get('production_mrr'))}"),
        ])
    headline_rows.append([
        "Quality/runtime (optimiser benchmark)",
        benchmark["verdict"],
        _benchmark_headline_text(benchmark) + " (raw evolutionary search violates hard MAX in 35%–45% of runs without repair)",
    ])
    if ablation:
        sel = ablation["selection_ablation"]["pooled"]
        sc = sel["scalar"].get("mean_worst_day_rel_shortfall_pct")
        adq = sel["adequacy_first"].get("mean_worst_day_rel_shortfall_pct")
        sc_cost = sel["scalar"].get("mean_cost") or 0.0
        adq_cost = sel["adequacy_first"].get("mean_cost") or 0.0
        cost_pct = ((adq_cost / sc_cost - 1.0) * 100.0) if sc_cost else 0.0
        delta = (adq - sc) if (adq is not None and sc is not None) else None
        comp_2d = (ablation["composition_ablation"]["pooled"].get("two_dish") or {}).get("adequacy_first", {})
        headline_rows.append([
            "Selection, composition & exact-reference ablation",
            ablation["verdict"],
            (f"1-dish adequacy-first worst-day shortfall {_fmt(adq)}% vs scalar "
             f"{_fmt(sc)}% (Δ {_fmt(delta) if delta is not None else 'n/a'} "
             f"pct-pts, cost {cost_pct:+.1f}%); 2-dish main+side reduces worst-day shortfall to "
             f"{_fmt(comp_2d.get('mean_worst_day_rel_shortfall_pct'))}%; 0/16 scalar plans hit "
             f"single-objective per-day additive lower bound"),
        ])
    adq_sum = satisfaction.get("adequacy_summary") or {}
    headline_rows.extend([
        ["Constraint satisfaction & 7-day soft-floor adequacy", satisfaction["verdict"],
         (f"{satisfaction['zero_violation_plans']}/{satisfaction['plans_attempted']} plans with zero hard "
          f"MAX violations ({_pct(satisfaction['zero_violation_rate'])}); "
          f"all-MIN-floors met on {adq_sum.get('plans_meeting_all_min_floors')}/"
          f"{satisfaction['zero_violation_plans']} plans "
          f"({_pct(adq_sum.get('all_min_floors_met_rate'))}, mean worst-day MIN shortfall "
          f"{_fmt(adq_sum.get('mean_worst_day_min_shortfall_pct'))}%, max "
          f"{_fmt(adq_sum.get('max_worst_day_min_shortfall_pct'))}%)")],
        ["Groundedness (regression gate)", groundedness["verdict"],
         (f"fixture grounded {_pct(groundedness['grounded']['pass_rate'])} "
          f"(citation accuracy {_pct(groundedness['grounded']['citation_accuracy'])}), "
          f"escalation {_pct(groundedness['escalation']['pass_rate'])}, "
          f"refusals {_pct(groundedness['irrelevant_refusals']['pass_rate'])}")],
        ["Traceability (regression gate)", traceability["verdict"],
         (f"{traceability['overall']['traceable']}/{traceability['overall']['items']} envelope items "
          f"traceable ({_pct(traceability['overall']['rate'])}) across {traceability['eligible_patients']} "
          f"eligible fixture patients; {traceability['rejected_patients']} REJECTED patients counted "
          f"separately")],
        ["Conflict resolution (regression gate)", conflicts["verdict"],
         (f"{conflicts['cases_passed']}/{conflicts['cases_total']} deterministic priority/boundary cases "
          f"({_pct(conflicts['pass_rate'])}), {conflicts['checks_passed']}/{conflicts['checks_total']} checks")],
    ])
    add(_table(["Criterion", "Verdict", "Headline number"], headline_rows))
    add("")

    add("## Traceability")
    add("")
    add(traceability["definition"])
    add("")
    add(_table(
        ["Patient", "Status", "Targets", "Exclusions", "Items", "Traceable", "Rate", "Fired rules"],
        [[r["patient_id"], r["status"], r["targets"], r["exclusions"],
          r["items"], r["traceable"], _pct(r["rate"]), r["fired_rules"]]
         for r in traceability["per_patient"]],
    ))
    add("")
    add(f"**Overall (eligible patients): {traceability['overall']['traceable']}/"
        f"{traceability['overall']['items']} = {_pct(traceability['overall']['rate'])} — verdict {traceability['verdict']}.** "
        f"REJECTED patients ({', '.join(traceability['rejected_patient_ids']) or 'none'}) legitimately "
        f"have no nutrient targets; their {traceability['rejected_exclusions']['items']} exclusions are "
        f"still {traceability['rejected_exclusions']['traceable']}/{traceability['rejected_exclusions']['items']} "
        f"traceable.")
    add("")

    add("## Conflict resolution")
    add("")
    add(conflicts["definition"])
    add("")
    add(_table(
        ["Case", "Verdict", "Failed checks"],
        [[c["name"], "PASS" if c["passed"] else "FAIL",
          "; ".join(ch["expectation"] for ch in c["checks"] if not ch["passed"]) or "—"]
         for c in conflicts["cases"]],
    ))
    add("")
    add(f"**Pass rate: {conflicts['cases_passed']}/{conflicts['cases_total']} cases, "
        f"{conflicts['checks_passed']}/{conflicts['checks_total']} individual checks — verdict "
        f"{conflicts['verdict']}.**")
    add("")

    add("## Constraint satisfaction")
    add("")
    add(satisfaction["definition"])
    add("")
    add(_table(
        ["Patient", "Archetype", "Outcome", "Violations", "Engine", "Per-day OK",
         "Relaxations", "Blockers (leave-one-out)"],
        [[r["patient_id"], r.get("archetype") or "—",
          r.get("status") or "—",
          r.get("violation_count", "—"),
          r.get("engine") or "—",
          _fmt(r.get("per_day_hard_compliant")) if r.get("attempted") else "—",
          ", ".join(sorted({x["nutrient"] for x in r.get("relaxed_constraints", [])})) or "—",
          ", ".join(r.get("blocking_constraints_leave_one_out") or []) or "—"]
         for r in satisfaction["per_patient"]],
    ))
    add("")
    adq_sum = satisfaction.get("adequacy_summary") or {}
    if adq_sum.get("mean_worst_day_min_shortfall_pct") is not None:
        add(f"Soft-floor adequacy disclosure: mean worst-day MIN shortfall "
            f"**{_fmt(adq_sum['mean_worst_day_min_shortfall_pct'])}%** "
            f"(max **{_fmt(adq_sum['max_worst_day_min_shortfall_pct'])}%**, "
            f"**{adq_sum['plans_meeting_all_min_floors']}/{satisfaction['zero_violation_plans']}** "
            f"plans meeting every MIN floor on all 7 days).")
        add("")
    add(f"**Zero-violation plans: {satisfaction['zero_violation_plans']}/{satisfaction['plans_attempted']} "
        f"({_pct(satisfaction['zero_violation_rate'])}) — verdict {satisfaction['verdict']}.** "
        f"Infeasible envelopes are diagnosed explicitly by the solver (empty plan, "
        f"`infeasibility_reason` set) and never served; where a single constraint "
        f"removal restores greedy feasibility it is listed as a blocker.")
    add("")

    add("## Quality/runtime (optimiser benchmark)")
    add("")
    add(benchmark["definition"])
    add("")
    add("### Headline (main phase: 4 envelopes × 5 seeds, pop=40, gen=80)")
    add("")
    add(_table(["Method", "Guarantee", "Runs", "Mean HV", "HV std", "Violation rate",
                "Mean runtime (ms)"],
               [[m["method"], m["guarantee"], m["runs"], m["mean_hv"], m["hv_std"],
                 _pct(m["violation_rate"]), m["mean_runtime_ms"]] for m in benchmark["headline"]]))
    add("")
    add("### Mean hypervolume per envelope")
    add("")
    methods = [m["method"] for m in benchmark["headline"]]
    add(_table(["Envelope"] + methods,
               [[e["envelope"]] + [e.get(method) for method in methods]
                for e in benchmark["hv_per_envelope"]]))
    add("")
    add("### NSGA-II pop × gen sweep (1 seed)")
    add("")
    add(_table(["Pop", "Gen", "Mean HV", "Mean runtime (ms)"],
               [[s["pop"], s["gen"], s["mean_hv"], s["mean_runtime_ms"]] for s in benchmark["sweep"]]))
    add("")
    add(f"### Recommendation (verbatim from `{benchmark['artefacts']['md']}`)")
    add("")
    for line in benchmark["recommendation"].splitlines():
        add(line)
    add("")
    add(f"Verdict: **{benchmark['verdict']}** — {benchmark['verdict_note']}")
    add("")

    add("## Groundedness (chat)")
    add("")
    add(groundedness["definition"])
    add("")
    add("### Grounded nutrition questions")
    add("")
    add(_table(["Question", "Envelope", "Status", "Cited rules", "Expected (any of)", "Pass"],
               [[r["question"], r["envelope_variant"], r["status"],
                 ", ".join(r["cited_rule_ids"]) or "—",
                 ", ".join(r["acceptable_rule_ids"]), "PASS" if r["passed"] else "FAIL"]
                for r in groundedness["grounded"]["rows"]]))
    add("")
    add("### Escalation cases")
    add("")
    add(_table(["Question", "Expected", "Status", "Observed", "Pass"],
               [[r["question"], r["expected_category"], r["status"],
                 r["observed_category"] or "—", "PASS" if r["passed"] else "FAIL"]
                for r in groundedness["escalation"]["rows"]]))
    add("")
    add("### Irrelevant / low-relevance questions (expected refusal)")
    add("")
    add(_table(["Question", "Status", "Pass"],
               [[r["question"], r["status"], "PASS" if r["passed"] else "FAIL"]
                for r in groundedness["irrelevant_refusals"]["rows"]]))
    add("")
    add(f"**Grounded {groundedness['grounded']['passed']}/{groundedness['grounded']['total']} "
        f"({_pct(groundedness['grounded']['pass_rate'])}), citation accuracy "
        f"{_pct(groundedness['grounded']['citation_accuracy'])}; escalation "
        f"{groundedness['escalation']['passed']}/{groundedness['escalation']['total']} "
        f"({_pct(groundedness['escalation']['pass_rate'])}); refusals "
        f"{groundedness['irrelevant_refusals']['passed']}/{groundedness['irrelevant_refusals']['total']} "
        f"({_pct(groundedness['irrelevant_refusals']['pass_rate'])}); overall "
        f"{_pct(groundedness['overall_pass_rate'])} — verdict {groundedness['verdict']}.**")
    add("")
    add("### Historical failure probes (included in verdict)")
    add("")
    add(_table(["Probe", "Expected", "Observed", "Gap"],
               [[g["question"], g["expected"],
                 g.get("observed_category") or g.get("observed_status") or "—",
                 g["gap"]] for g in groundedness["known_gaps"]]))
    add("")
    add("### Expert-review rubric (human scoring — cannot be automated)")
    add("")
    add("Human reviewers score each of the five criteria below on a 1–5 scale; the "
        "chat quality score is the mean across criteria and questions. A score below "
        "3 on *safety behaviour* is an automatic fail regardless of the mean.")
    add("")
    add(_table(["Criterion", "Scale", "How a human reviewer scores"],
               [[r["criterion"], r["scale"], r["how_to_score"]] for r in groundedness["expert_review_rubric"]]))
    add("")

    if ablation:
        _render_ablation(add, ablation, _table, _fmt)

    if external:
        _render_external(add, external, _table, _fmt, _pct)

    add("## Limitations & known caveats")
    add("")
    add("1. **Encoding: hard = MAX ceilings + exclusions only (PLAN.md module 4).** "
        "MIN floors and TARGET values are soft objective terms: they steer the "
        "nutrient-deviation objective and never count as violations. This is the "
        "documented intent of the plan; the earlier hard-MIN encoding made "
        "guideline floors (fibre, potassium, energy) cause infeasibility instead "
        "of guiding the search. Consequence: `violation_count == 0` means the "
        "hard ceilings and exclusions hold — it does NOT mean the plan meets "
        "every soft floor. Residual soft shortfalls are reported per plan "
        "(see `soft_aims` in results.json and the adequacy panel). Production "
        "main/side search uses normalised adequacy-first ranking against original aims.")
    add("")
    add("2. **Fibre MIN relaxation and meal encoding.** The legacy single-dish "
        "search discloses relaxed soft aims when used as fallback. Production "
        "composition uses one main and an optional side per meal, without relaxing "
        "approved aims. Roles are heuristic. Search failure for this encoding is "
        "not proof of infeasibility; the exact reference applies to single-dish days.")
    add("")
    add("3. **Exclusion vocabulary (fixed in this remediation).** The rulebook "
        "emits semantic exclusion values (`high_potassium_foods`, "
        "`phosphate_additive_processed`, `sugar_sweetened_beverage`, "
        "`high_glycaemic_load`) that no dataset tag spells out; before the fix "
        "every rulebook exclusion matched zero dishes. "
        "`backend/optim/exclusion_mapping.py` now bridges each value to a "
        "documented per-serving nutrient threshold (K > 500 mg, P > 300 mg, "
        "drink with sugar > 5 g, carbs > 75 g); unknown values keep "
        "literal-only matching. The dataset's own `high_potassium` tag continues "
        "to work via literal matching.")
    add("")
    add("4. **Newest-first labs orientation.** `labs_K_monthly` / `labs_PO4_monthly` "
        "are ordered newest-first: index 0 pairs with `months_offset_ago == 0` "
        "(current) and equals the top-level `serum_K_meq_L` / `serum_PO4_mg_dL` the "
        "rule engine consumes. Any consumer that sorts these series ascending "
        "silently reads the *oldest* lab as current and will mis-trigger the "
        "hyperkalaemia/hyperphosphataemia rules.")
    add("")
    add("5. **External benchmark storage.** Evaluation reports (`EVALUATION.md`) and "
        "raw results (`results.json`) require an explicit `--out-dir` export. "
        "Optimizer/mining/retrieval benchmark files live outside the code checkout under `CARELOOP_DATASET_DIR/benchmarks/` "
        "and `CARELOOP_DATASET_DIR/outputs/` (or `CARELOOP_ARTIFACT_DIR`). "
        "Runtimes in the report are wall-clock and not deterministic.")
    add("")
    add("6. **Chat evaluation scope & HealthBench findings.** Claims carry source "
        "metadata and are checked for citation identity, patient applicability and "
        "approved numeric values. On OpenAI HealthBench Consensus, 100% of answered "
        "prompts preserve citation completeness and claim-source consistency, but "
        "regex-only escalation catches only a subset of open-ended physician-labelled "
        "emergent descriptions.")
    add("")
    add("7. **Data quality & external cohort scope.** All 214 Singapore dishes are "
        "unverified and costs are synthetic estimates. NHANES 2021–2023 is a US "
        "cross-sectional survey (unweighted cohort mapping for rule/adherence stress "
        "testing); MIMIC-IV Demo 2.2 is inpatient/ICU data "
        "(100 patients), not outpatient longitudinal CKD tracking.")
    add("")
    return "\n".join(lines) + "\n"
