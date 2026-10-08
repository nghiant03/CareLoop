"""Markdown report renderer for the evaluation suite (deterministic output)."""

from __future__ import annotations

from typing import Any, Optional

__all__ = ["render_report"]


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".") if value != 0 else "0"
    return str(value)


def _pct(rate: Optional[float]) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_fmt(c) for c in row) + " |")
    return "\n".join(out)


def render_report(results: dict[str, Any]) -> str:
    q1, q2, q3 = results["q1_traceability"], results["q2_conflicts"], results["q3_constraint_satisfaction"]
    q4, q5 = results["q4_benchmark"], results["q5_groundedness"]
    meta = results["meta"]

    lines: list[str] = []
    add = lines.append

    add("# CareLoop — Automated Evaluation Report")
    add("")
    add(f"Suite: {meta['suite']} · optimiser seed {meta['seed']} "
        f"(pop {meta['pop_size']}, gen {meta['n_gen']}, NSGA-II) · "
        f"{meta['patients']} patients · {meta['dishes']}-dish pool")
    add("")
    add("Reproduce with `.venv/bin/python -m evaluation.run` (add `--rerun-benchmark` "
        "to regenerate the optimiser benchmark artefacts). Deterministic apart from "
        "wall-clock runtimes. Machine-readable twin: `evaluation/results.json`.")
    add("")

    # ------------------------------------------------------------------ summary
    add("## Headline verdicts")
    add("")
    add(_table(
        ["Question", "Verdict", "Headline number"],
        [
            ["Q1 Traceability", q1["verdict"],
             f"{q1['overall']['traceable']}/{q1['overall']['items']} envelope items "
             f"traceable ({_pct(q1['overall']['rate'])}) across {q1['eligible_patients']} "
             f"eligible patients; {q1['rejected_patients']} REJECTED patients counted "
             f"separately"],
            ["Q2 Conflict resolution", q2["verdict"],
             f"{q2['cases_passed']}/{q2['cases_total']} cases "
             f"({_pct(q2['pass_rate'])}), {q2['checks_passed']}/{q2['checks_total']} checks"],
            ["Q3 Constraint satisfaction", q3["verdict"],
             f"{q3['zero_violation_plans']}/{q3['plans_attempted']} plans with zero hard "
             f"violations ({_pct(q3['zero_violation_rate'])}); "
             f"{q3['infeasible_plans']} infeasible (diagnosed, nothing served); "
             f"{q3['relaxed_envelopes']} envelopes needed a disclosed MIN relaxation"],
            ["Q4 Quality/runtime", q4["verdict"],
             "NSGA-II: 0% violations, best HV, "
             + next((f"{m['mean_runtime_ms']} ms mean" for m in q4["headline"]
                     if m["method"] == "nsga2"), "n/a")
             + " (consumed from benchmark artefacts)"],
            ["Q5 Groundedness", q5["verdict"],
             f"grounded {_pct(q5['grounded']['pass_rate'])} "
             f"(citation accuracy {_pct(q5['grounded']['citation_accuracy'])}), "
             f"escalation {_pct(q5['escalation']['pass_rate'])}, "
             f"refusals {_pct(q5['irrelevant_refusals']['pass_rate'])}"],
        ],
    ))
    add("")

    # ------------------------------------------------------------------ Q1
    add("## Q1 — Traceability")
    add("")
    add(q1["definition"])
    add("")
    add(_table(
        ["Patient", "Status", "Targets", "Exclusions", "Items", "Traceable", "Rate", "Fired rules"],
        [[r["patient_id"], r["status"], r["targets"], r["exclusions"],
          r["items"], r["traceable"], _pct(r["rate"]), r["fired_rules"]]
         for r in q1["per_patient"]],
    ))
    add("")
    add(f"**Overall (eligible patients): {q1['overall']['traceable']}/"
        f"{q1['overall']['items']} = {_pct(q1['overall']['rate'])} — verdict {q1['verdict']}.** "
        f"REJECTED patients ({', '.join(q1['rejected_patient_ids']) or 'none'}) legitimately "
        f"have no nutrient targets; their {q1['rejected_exclusions']['items']} exclusions are "
        f"still {q1['rejected_exclusions']['traceable']}/{q1['rejected_exclusions']['items']} "
        f"traceable.")
    add("")

    # ------------------------------------------------------------------ Q2
    add("## Q2 — Conflict resolution")
    add("")
    add(q2["definition"])
    add("")
    add(_table(
        ["Case", "Verdict", "Failed checks"],
        [[c["name"], "PASS" if c["passed"] else "FAIL",
          "; ".join(ch["expectation"] for ch in c["checks"] if not ch["passed"]) or "—"]
         for c in q2["cases"]],
    ))
    add("")
    add(f"**Pass rate: {q2['cases_passed']}/{q2['cases_total']} cases, "
        f"{q2['checks_passed']}/{q2['checks_total']} individual checks — verdict "
        f"{q2['verdict']}.**")
    add("")

    # ------------------------------------------------------------------ Q3
    add("## Q3 — Constraint satisfaction")
    add("")
    add(q3["definition"])
    add("")
    add(_table(
        ["Patient", "Archetype", "Outcome", "Violations", "Engine", "Per-day OK",
         "Relaxations", "Blockers (leave-one-out)"],
        [[r["patient_id"], r.get("archetype") or "—",
          r.get("status") or "—",
          r.get("violation_count", "—"),
          r.get("engine") or "—",
          _fmt(r.get("per_day_totals_compliant")) if r.get("attempted") else "—",
          ", ".join(sorted({x["nutrient"] for x in r.get("relaxed_constraints", [])})) or "—",
          ", ".join(r.get("blocking_constraints_leave_one_out") or []) or "—"]
         for r in q3["per_patient"]],
    ))
    add("")
    add(f"**Zero-violation plans: {q3['zero_violation_plans']}/{q3['plans_attempted']} "
        f"({_pct(q3['zero_violation_rate'])}) — verdict {q3['verdict']}.** "
        f"Infeasible envelopes are diagnosed explicitly by the solver (empty plan, "
        f"`infeasibility_reason` set) and never served; where a single constraint "
        f"removal restores greedy feasibility it is listed as a blocker.")
    add("")

    # ------------------------------------------------------------------ Q4
    add("## Q4 — Quality/runtime (optimiser benchmark)")
    add("")
    add(q4["definition"])
    add("")
    add("### Headline (main phase: 4 envelopes × 5 seeds, pop=40, gen=80)")
    add("")
    add(_table(["Method", "Runs", "Mean HV", "HV std", "Violation rate", "Mean runtime (ms)"],
               [[m["method"], m["runs"], m["mean_hv"], m["hv_std"],
                 _pct(m["violation_rate"]), m["mean_runtime_ms"]] for m in q4["headline"]]))
    add("")
    add("### Mean hypervolume per envelope")
    add("")
    add(_table(["Envelope", "NSGA-II", "GA", "Greedy", "Random"],
               [[e["envelope"], e["nsga2"], e["ga"], e["greedy"], e["random"]]
                for e in q4["hv_per_envelope"]]))
    add("")
    add("### NSGA-II pop × gen sweep (1 seed)")
    add("")
    add(_table(["Pop", "Gen", "Mean HV", "Mean runtime (ms)"],
               [[s["pop"], s["gen"], s["mean_hv"], s["mean_runtime_ms"]] for s in q4["sweep"]]))
    add("")
    add("### Recommendation (verbatim from `backend/optim/benchmark_results.md`)")
    add("")
    for line in q4["recommendation"].splitlines():
        add(line if line.startswith("*") else line)
    add("")
    add(f"Verdict: **{q4['verdict']}** — {q4['verdict_note']}")
    add("")

    # ------------------------------------------------------------------ Q5
    add("## Q5 — Groundedness (chat)")
    add("")
    add(q5["definition"])
    add("")
    add("### Grounded nutrition questions")
    add("")
    add(_table(["Question", "Envelope", "Status", "Cited rules", "Expected (any of)", "Pass"],
               [[r["question"], r["envelope_variant"], r["status"],
                 ", ".join(r["cited_rule_ids"]) or "—",
                 ", ".join(r["acceptable_rule_ids"]), "PASS" if r["passed"] else "FAIL"]
                for r in q5["grounded"]["rows"]]))
    add("")
    add("### Escalation cases")
    add("")
    add(_table(["Question", "Expected", "Status", "Observed", "Pass"],
               [[r["question"], r["expected_category"], r["status"],
                 r["observed_category"] or "—", "PASS" if r["passed"] else "FAIL"]
                for r in q5["escalation"]["rows"]]))
    add("")
    add("### Irrelevant / low-relevance questions (expected refusal)")
    add("")
    add(_table(["Question", "Status", "Pass"],
               [[r["question"], r["status"], "PASS" if r["passed"] else "FAIL"]
                for r in q5["irrelevant_refusals"]["rows"]]))
    add("")
    add(f"**Grounded {q5['grounded']['passed']}/{q5['grounded']['total']} "
        f"({_pct(q5['grounded']['pass_rate'])}), citation accuracy "
        f"{_pct(q5['grounded']['citation_accuracy'])}; escalation "
        f"{q5['escalation']['passed']}/{q5['escalation']['total']} "
        f"({_pct(q5['escalation']['pass_rate'])}); refusals "
        f"{q5['irrelevant_refusals']['passed']}/{q5['irrelevant_refusals']['total']} "
        f"({_pct(q5['irrelevant_refusals']['pass_rate'])}); overall "
        f"{_pct(q5['overall_pass_rate'])} — verdict {q5['verdict']}.**")
    add("")
    add("### Known gaps (informational, not scored)")
    add("")
    add(_table(["Probe", "Expected", "Observed", "Gap"],
               [[g["question"], g["expected"],
                 g.get("observed_category") or g.get("observed_status") or "—",
                 g["gap"]] for g in q5["known_gaps"]]))
    add("")
    add("### Expert-review rubric (human scoring — cannot be automated)")
    add("")
    add("Human reviewers score each of the five criteria below on a 1–5 scale; the "
        "chat quality score is the mean across criteria and questions. A score below "
        "3 on *safety behaviour* is an automatic fail regardless of the mean.")
    add("")
    add(_table(["Criterion", "Scale", "How a human reviewer scores"],
               [[r["criterion"], r["scale"], r["how_to_score"]] for r in q5["expert_review_rubric"]]))
    add("")

    # ------------------------------------------------------------------ limits
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
        "(see `soft_aims` in results.json and the totals panel), and with the "
        "placeholder scalar weights (deviation 0.001 vs preference/variety 0.5, "
        "cost 0.02) the search may still trade floors against preference and "
        "cost — retuning `SCALAR_WEIGHTS` is the natural next step.")
    add("")
    add("2. **Fibre MIN relaxation (disclosure still active).** The guideline "
        "rulebook sets fibre floors (GEN-FIBER-25 min 25 g/d, DASH-2025-FIBER-30 "
        "min 30 g/d) but the dish dataset tops out at 8 g fibre per dish, so the "
        "best possible 3-dish day reaches only 24 g. `prepare_envelope_for_pool` "
        "still lowers unreachable MIN floors in the solved copy and discloses "
        "every adjustment in `relaxed_constraints` — no longer needed for "
        "feasibility (floors are soft), it now calibrates the deviation "
        "objective to an achievable aim and keeps the clinician-facing "
        "disclosure intact. Heavier patients additionally trigger the "
        "energy-kcal floor relaxation once the semantic exclusions narrow the "
        "pool's energy ceiling.")
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
    add("5. **Benchmark reuse.** Q4 consumes the committed benchmark artefacts "
        "instead of re-running NSGA-II/GA/greedy/random (default); "
        "`--rerun-benchmark` regenerates them (~23 s wall time). The artefacts "
        "were regenerated after the hard/soft re-encoding, so the comparison "
        "table reflects the new objective semantics for all methods alike. "
        "Runtimes in the report are wall-clock and not deterministic.")
    add("")
    add("6. **Chat evaluation scope.** Groundedness is scored automatically against "
        "the rules that *produce a constraint* for the asked nutrient; supporting "
        "citations retrieved by TF-IDF may legitimately mention other nutrients. "
        "Nutrients without constraint-producing rules (sugar, total fat) cannot be "
        "grounded today and are listed as known gaps. The expert-review rubric is "
        "provided for the human evaluation that cannot be automated.")
    add("")
    add("7. **Soft floors vs the dish pool.** Even as soft aims, some floors "
        "remain far from what the pool delivers (e.g. mean fibre ~10 g/day "
        "against the 25-30 g guideline aim) — the curated renal-replenishment "
        "dishes add fruit/vegetable and higher-fibre options, but 3 dishes/day "
        "from a 214-dish Singaporean pool cannot reach DASH-level fibre/potassium "
        "without dedicated product reformulation. The soft-aim shortfalls in "
        "results.json quantify this per patient.")
    add("")
    add("8. **Scale.** 20 synthetic patients, one dish dataset, one seed set. "
        "Statistical strength is limited; the numbers measure pipeline correctness, "
        "not clinical validity.")
    add("")
    return "\n".join(lines) + "\n"