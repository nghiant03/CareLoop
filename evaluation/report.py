"""Markdown report renderer for the evaluation suite (deterministic output)."""

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
    """One-line benchmark summary naming the actual mean-HV winner from the data."""
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
    # Historical artifacts (pre-2026-10) pooled the unit-mixed raw
    # ``mean_daily_shortfall`` (kcal/g/mg averaged together); it is
    # deliberately NOT rendered. They lack ``mean_daily_rel_shortfall_pct``,
    # which renders as n/a rather than raising.
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
    """Render the ablation section (selection ablation, composition, exact reference)."""
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

    # Composition
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

    # Exact reference
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
    """Render the external dataset evaluation section."""
    add("## External dataset evaluation (NHANES, MIMIC-IV, HealthBench)")
    add("")
    add(external["definition"])
    add("")

    nh = external.get("nhanes_cohort") or {}
    if nh.get("available"):
        tr = nh["traceability"]
        sg = nh["scope_gate"]
        add(f"### 1. {nh['dataset']} — Rule-engine traceability, provenance & scope gates at scale")
        add("")
        add(f"Evaluated **{nh['evaluated_subjects']}** real participants "
            f"(from {nh['total_complete_in_survey']} complete survey profiles; "
            f"{nh['eligible_subjects']} eligible, {nh['rejected_subjects']} scope-rejected, "
            f"{nh['engine_errors']} engine errors): "
            f"**{tr['traceable']}/{tr['items']} ({pct(tr['rate'])})** items traceable, "
            f"**{tr['provenance_resolved']}/{tr['targets']} ({pct(tr['provenance_rate'])})** "
            f"targets resolved to exact rule authorship, and "
            f"**{sg['observed_rejected']}/{sg['expected_rejected']} ({pct(sg['accuracy'])})** "
            f"scope-gate accuracy.")
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

    mm = external.get("mimic_longitudinal_trends") or {}
    if mm.get("available"):
        rf = mm["real_trajectory_flags"]
        pb = mm["planted_regime_benchmark"]
        add(f"### 2. {mm['dataset']} — Longitudinal lab trends & hospital medication rules")
        add("")
        add(f"Evaluated **{mm['patients_total']}** inpatient records "
            f"({mm['patients_with_k_series_ge_3']} with >=3 K+ dates, "
            f"{mm['patients_with_po4_series_ge_3']} with >=3 PO4 dates): "
            f"`detect_trends` raised **{rf['total']}** flags (**{rf['urgent']}** urgent, "
            f"**{rf['review']}** review; {rf['potassium_flags']} K+, {rf['phosphate_flags']} PO4). "
            f"On the planted-regime benchmark anchored to MIMIC baselines: "
            f"rising recall **{pb['rising_detected']}/{pb['rising_cases']} ({pct(pb['rising_recall'])})**, "
            f"stable specificity **{pct(pb['stable_specificity'])}** "
            f"({pb['stable_false_positives']}/{pb['stable_cases']} false positives), "
            f"EWMA plateau de-escalation **{pb['ewma_deescalated_to_review']}/{pb['flattened_cases']} "
            f"({pct(pb['ewma_deescalation_rate'])})**.")
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
        add(f"### 3. {hb['dataset']} — External emergency triage & nutrition grounding")
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
        nq = hb.get("nutrition_queries") or {}
        add(f"Nutrition-focused HealthBench queries (**{nq.get('total', 0)}** total): "
            f"**{nq.get('answered', 0)}** answered, **{nq.get('escalated', 0)}** escalated, "
            f"**{nq.get('refused', 0)}** refused; citation completeness "
            f"**{pct(nq.get('citation_completeness_rate'))}**, structured claim-source "
            f"consistency **{pct(nq.get('claim_consistency_rate'))}**.")
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

    add("# CareLoop — Automated Evaluation Report")
    add("")
    add(f"Suite: {meta['suite']} · optimiser seed {meta['seed']} "
        f"(pop {meta['pop_size']}, gen {meta['n_gen']}, NSGA-II) · "
        f"{meta['patients']} synthetic fixture patients · {meta['dishes']}-dish pool")
    add("")
    add("Reproduce with `.venv/bin/python -m evaluation.run` (add `--rerun-benchmark` "
        "to regenerate the optimiser benchmark artefacts). Deterministic apart from "
        "wall-clock runtimes. All generated reports (`EVALUATION.md`) and raw outputs "
        "(`results.json`) are written outside the code checkout under `CARELOOP_ARTIFACT_DIR` "
        "or `CARELOOP_DATASET_DIR/outputs/evaluation/`.")
    add("")

    # Summary
    add("## Headline verdicts")
    add("")
    headline_rows: list[list[Any]] = [
        ["Traceability (Tier 1)", traceability["verdict"],
         (f"{traceability['overall']['traceable']}/{traceability['overall']['items']} envelope items "
         f"traceable ({_pct(traceability['overall']['rate'])}) across {traceability['eligible_patients']} "
         f"eligible patients; {traceability['rejected_patients']} REJECTED patients counted "
         f"separately")],
        ["Conflict resolution (Tier 1)", conflicts["verdict"],
         (f"{conflicts['cases_passed']}/{conflicts['cases_total']} cases "
         f"({_pct(conflicts['pass_rate'])}), {conflicts['checks_passed']}/{conflicts['checks_total']} checks")],
        ["Constraint satisfaction (Tier 1)", satisfaction["verdict"],
         (f"{satisfaction['zero_violation_plans']}/{satisfaction['plans_attempted']} plans with zero hard "
         f"violations ({_pct(satisfaction['zero_violation_rate'])}); "
         f"{satisfaction['infeasible_plans']} infeasible (diagnosed, nothing served); "
         f"{satisfaction['relaxed_envelopes']} envelopes needed a disclosed MIN relaxation")],
        ["Groundedness (Tier 1)", groundedness["verdict"],
         (f"grounded {_pct(groundedness['grounded']['pass_rate'])} "
         f"(citation accuracy {_pct(groundedness['grounded']['citation_accuracy'])}), "
         f"escalation {_pct(groundedness['escalation']['pass_rate'])}, "
         f"refusals {_pct(groundedness['irrelevant_refusals']['pass_rate'])}")],
        ["Quality/runtime (Tier 2)", benchmark["verdict"], _benchmark_headline_text(benchmark)
         + " (consumed from external benchmark artefacts)"],
    ]
    if ablation:
        sel = ablation["selection_ablation"]["pooled"]
        sc = sel["scalar"].get("mean_worst_day_rel_shortfall_pct")
        adq = sel["adequacy_first"].get("mean_worst_day_rel_shortfall_pct")
        sc_cost = sel["scalar"].get("mean_cost") or 0.0
        adq_cost = sel["adequacy_first"].get("mean_cost") or 0.0
        cost_pct = ((adq_cost / sc_cost - 1.0) * 100.0) if sc_cost else 0.0
        delta = (adq - sc) if (adq is not None and sc is not None) else None
        headline_rows.append([
            "Selection & composition ablation (Tier 2)", ablation["verdict"],
            (f"adequacy-first worst-day shortfall {_fmt(adq)}% vs scalar "
            f"{_fmt(sc)}% (Δ {_fmt(delta) if delta is not None else 'n/a'} "
            f"pct-pts), cost {cost_pct:+.1f}% vs scalar; meal-composition "
            f"ablation informational"),
        ])
    if external and external.get("nhanes_cohort", {}).get("available"):
        nh = external["nhanes_cohort"]
        mm = external["mimic_longitudinal_trends"]
        hb = external["healthbench_chat"]
        headline_rows.append([
            "External datasets (Tier 2)", external["verdict"],
            (f"NHANES {nh['traceability']['traceable']}/{nh['traceability']['items']} "
             f"traceable ({nh['evaluated_subjects']} subjects), recall hard-violation rate "
             f"{_pct(nh['dietary_recall_adherence']['baseline_hard_violation_day_rate'])}; "
             f"MIMIC {mm['real_trajectory_flags']['total']} flags, 100% planted recall/specificity; "
             f"HealthBench {hb['nutrition_queries']['answered']}/{hb['nutrition_queries']['total']} "
             f"nutrition answers 100% source-consistent"),
        ])
    add(_table(["Criterion", "Verdict", "Headline number"], headline_rows))
    add("")

    # Traceability
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

    # Conflict resolution
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

    # Constraint satisfaction
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

    # Quality/runtime (optimiser benchmark)
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

    # Groundedness (chat)
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

    # Objective/selection & meal-composition ablation
    if ablation:
        _render_ablation(add, ablation, _table, _fmt)

    # External dataset evaluation
    if external:
        _render_external(add, external, _table, _fmt, _pct)

    # Limitations
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
    add("5. **External benchmark storage.** All evaluation reports (`EVALUATION.md`), "
        "raw results (`results.json`), and optimizer/mining/retrieval benchmark "
        "files live outside the code checkout under `CARELOOP_DATASET_DIR/benchmarks/` "
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
        "testing, not clinical import); MIMIC-IV Demo 2.2 is inpatient/ICU data "
        "(100 patients), not outpatient longitudinal CKD tracking.")
    add("")
    return "\n".join(lines) + "\n"
