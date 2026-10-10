"""Benchmark harness: multi-algorithm comparison on the real dish dataset.

Run::

    .venv/bin/python -m backend.optim.benchmark

Design
------
* 4 representative APPROVED envelopes (``backend.optim.envelopes``):
  ``ckd_strict``, ``ckd_hyperkalemia``, ``t2d_htn``, ``t2d_only``.
* Main comparison — 5 seeds each.  Method families:

  - Guaranteed pymoo methods (through ``solver.solve`` and therefore the
    hard feasibility guarantee / repair / greedy fallback): NSGA-II
    (production), NSGA-III, MOEA/D, AGE-MOEA, SMSEMOA.
  - Raw pymoo methods (``solve(..., guarantee=False)``): the same five
    algorithms on the untouched search front, so honest hard-constraint
    violation rates are measurable (labelled ``<method>-raw``).
  - Raw baselines (never guaranteed): hand-rolled GA, greedy construction,
    random search.

  Hard constraints are MAX ceilings + exclusions; MIN
  floors / TARGETs are soft objective terms for all methods alike.

* Algorithm configuration (4 objectives, pop=40, gen=80 unless noted):
  NSGA-III  — das-dennis reference directions p=4 (35 directions),
              IntegerRandomSampling + SBX + PM (same operators as NSGA-II so
              the comparison isolates the survival mechanism).
  MOEA/D    — the same 35 das-dennis weight vectors, T=15 neighbours, PBI
              decomposition (theta=5), neighbourhood mating p=0.9.  pymoo's
              MOEA/D cannot encode inequality constraints, so it optimises the
              unconstrained view (objectives unchanged); population is tied to
              the weight-vector count (35).
  AGE-MOEA  — geometry-adaptive survival (numba-backed), default alpha
              estimation; same operators as NSGA-II.
  SMSEMOA   — exact hypervolume-contribution survival in 4-D, pop=40 to bound
              the per-generation HV cost.
  RNSGA-II was considered and skipped: its reference point must be calibrated
  in raw objective units per envelope (preference-driven method); SMSEMOA
  covers the "indicator-based" corner at far lower setup risk.

* Hypervolume: pymoo's exact HV indicator on min-max normalised objectives.
  Bounds are computed per envelope across ALL feasible fronts from the main
  phase (all methods/seeds, guaranteed and raw) and reused for the sweep;
  reference point is 1.1^4.  A run with no feasible plan scores HV = 0.
* NSGA-II population/generation sweep: pop {20,40,80} x gen {40,80,160},
  1 seed, scored against the main-phase bounds (unchanged from the original
  harness; the production default stays NSGA-II).

Outputs: ``backend/optim/benchmark_results.csv`` (per-run rows) and
``backend/optim/benchmark_results.md`` (summary tables + recommendation).

Set ``CARELOOP_BENCH_SMOKE=1`` for a fast smoke run (1 seed, 1 envelope,
tiny budgets) written to ``benchmark_results_smoke.{csv,md}`` — used by the
test-suite to verify artifact regeneration without clobbering full results.
"""

from __future__ import annotations

import csv
import os
import statistics
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

from backend.optim.envelopes import build_benchmark_envelopes  # noqa: E402
from backend.optim.problem import OBJECTIVE_NAMES  # noqa: E402
from backend.optim.real_data import load_dishes  # noqa: E402
from backend.optim.solver import HAS_PYMOO, solve  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "benchmark_results.csv")
MD_PATH = os.path.join(_HERE, "benchmark_results.md")

SMOKE = os.environ.get("CARELOOP_BENCH_SMOKE") == "1"
if SMOKE:  # smoke artifacts land in separate files so full results survive
    CSV_PATH = os.path.join(_HERE, "benchmark_results_smoke.csv")
    MD_PATH = os.path.join(_HERE, "benchmark_results_smoke.md")

SEEDS = [1, 2, 3, 4, 5]
if SMOKE:  # smoke: single seed so the test-suite regeneration check stays fast
    SEEDS = [1]
POP_SIZE = 40
N_GEN = 80
# Guaranteed pymoo methods (through the solver's feasibility guarantee)...
PYMOO_METHODS = ["nsga2", "nsga3", "moead", "age", "sms"]
# ...each also run raw (honest violation rate), plus the original baselines.
RAW_METHODS = [f"{m}-raw" for m in PYMOO_METHODS] + ["ga", "greedy", "random"]
# Display / report order for the full comparison table.
METHOD_ORDER = PYMOO_METHODS + [f"{m}-raw" for m in PYMOO_METHODS] + [
    "ga", "greedy", "random"
]
SWEEP_POP = [20, 40, 80]
SWEEP_GEN = [40, 80, 160]
SWEEP_SEED = 42
REF_MARGIN = 1.1


def _run(method: str, env, dishes, seed: int, pop_size: int, n_gen: int) -> dict:
    budget = os.environ.get("CARELOOP_BENCH_BUDGET", "evaluations")
    termination = (("time", float(os.environ.get("CARELOOP_BENCH_SECONDS", "0.5")))
                   if budget == "time" else ("n_eval", pop_size * n_gen))
    options = {"termination": termination} if method.removesuffix("-raw") in PYMOO_METHODS else {}
    if method.endswith("-raw") and method[:-4] in PYMOO_METHODS:
        return solve(
            env, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen,
            method=method[:-4], guarantee=False, **options,
        )
    return solve(env, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen, method=method, **options)


def _is_guaranteed(method: str) -> bool:
    return method in PYMOO_METHODS


def _feasible_F(result: dict) -> np.ndarray:
    rows = []
    front = result.get("front") or []
    if not front and result.get("plan"):
        front = [result]
    for entry in front:
        if entry.get("feasible"):
            rows.append([entry["objectives"][k] for k in OBJECTIVE_NAMES])
    return np.array(rows) if rows else np.zeros((0, len(OBJECTIVE_NAMES)))


def _normalisation_bounds(all_F: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.vstack([f for f in all_F if len(f)])
    lo = stacked.min(axis=0)
    hi = stacked.max(axis=0)
    hi = np.where(hi - lo < 1e-12, lo + 1.0, hi)
    return lo, hi


def _hypervolume(F: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    if len(F) == 0:
        return 0.0
    from pymoo.indicators.hv import HV

    norm = (F - lo) / (hi - lo)
    ref_point = np.full(len(OBJECTIVE_NAMES), REF_MARGIN)
    return float(HV(ref_point=ref_point).do(norm))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def main() -> int:
    t_start = time.perf_counter()
    dishes = load_dishes()
    envelopes = build_benchmark_envelopes()
    if SMOKE:
        envelopes = {k: envelopes[k] for k in sorted(envelopes)[:1]}
    if not HAS_PYMOO:
        print("WARNING: pymoo unavailable — NSGA-II rows will use the GA fallback engine")
        print("WARNING: pymoo comparison methods (nsga3/moead/age/sms) require pymoo")

    # rows: list of (row_dict, F_matrix)
    entries: list[tuple[dict, np.ndarray]] = []

    # ------------------------------------------------------------------
    # Phase 1: main comparison (envelopes x seeds x all methods)
    # ------------------------------------------------------------------
    n_envs = len(envelopes)
    n_runs = n_envs * len(SEEDS) * (len(PYMOO_METHODS) * 2 + 3)
    print("=" * 78)
    print(
        f"Phase 1: main comparison — {n_envs} envelope(s) x {len(SEEDS)} seed(s) x "
        f"{n_runs // (n_envs * len(SEEDS))} methods (guaranteed + raw + baselines)"
    )
    print("=" * 78)
    for env_name, env in envelopes.items():
        for seed in SEEDS:
            for method in METHOD_ORDER:
                result = _run(method, env, dishes, seed, POP_SIZE, N_GEN)
                F = _feasible_F(result)
                entries.append(
                    (
                        {
                            "phase": "main",
                            "envelope": env_name,
                            "envelope_id": env.envelope_id,
                            "method": method,
                            "seed": seed,
                            "pop_size": POP_SIZE,
                            "n_gen": N_GEN,
                            "evaluations": result["evaluations"],
                            "guaranteed": int(_is_guaranteed(method)),
                            "violation_count": result["violation_count"],
                            "feasible": int(bool(result["feasible"])),
                            "runtime_ms": round(result["runtime_ms"], 1),
                            "front_size": result["front_size"],
                            "engine": result.get("engine", method),
                            "hypervolume": "",
                        },
                        F,
                    )
                )
                print(
                    f"  {env_name:>16s} seed={seed} {method:>12s}"
                    f"  feasible={result['feasible']!s:>5}"
                    f"  viol={result['violation_count']:>3}"
                    f"  front={result['front_size']:>3}"
                    f"  runtime={result['runtime_ms']:>8.1f} ms"
                )

    # Per-envelope normalisation bounds over ALL feasible fronts (main phase,
    # guaranteed AND raw — one shared yardstick per envelope).
    bounds: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for env_name in envelopes:
        env_Fs = [F for (row, F) in entries if row["envelope"] == env_name and len(F)]
        bounds[env_name] = _normalisation_bounds(env_Fs) if env_Fs else (
            np.zeros(len(OBJECTIVE_NAMES)), np.ones(len(OBJECTIVE_NAMES))
        )

    # ------------------------------------------------------------------
    # Phase 2: NSGA-II population/generation sweep (production tuning)
    # ------------------------------------------------------------------
    if not SMOKE:
        print("=" * 78)
        print("Phase 2: NSGA-II pop x gen sweep — 4 envelopes x 1 seed x 9 configs")
        print("=" * 78)
        for env_name, env in envelopes.items():
            for pop_size in SWEEP_POP:
                for n_gen in SWEEP_GEN:
                    result = _run("nsga2", env, dishes, SWEEP_SEED, pop_size, n_gen)
                    F = _feasible_F(result)
                    entries.append(
                        (
                            {
                                "phase": "sweep",
                                "envelope": env_name,
                                "envelope_id": env.envelope_id,
                                "method": "nsga2-sweep",
                                "seed": SWEEP_SEED,
                                "pop_size": pop_size,
                                "n_gen": n_gen,
                                "evaluations": result["evaluations"],
                                "guaranteed": 1,
                                "violation_count": result["violation_count"],
                                "feasible": int(bool(result["feasible"])),
                                "runtime_ms": round(result["runtime_ms"], 1),
                                "front_size": result["front_size"],
                                "engine": result.get("engine", "nsga2"),
                                "hypervolume": "",
                            },
                            F,
                        )
                    )
                    print(
                        f"  {env_name:>16s} pop={pop_size:>3} gen={n_gen:>4}"
                        f"  feasible={result['feasible']!s:>5}"
                        f"  front={result['front_size']:>3}"
                        f"  runtime={result['runtime_ms']:>8.1f} ms"
                    )

    # ------------------------------------------------------------------
    # Score hypervolumes (sweep reuses the envelope's main-phase bounds)
    # ------------------------------------------------------------------
    for row, F in entries:
        lo, hi = bounds[row["envelope"]]
        row["hypervolume"] = f"{_hypervolume(F, lo, hi):.6f}"

    runtime_total = time.perf_counter() - t_start

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(entries[0][0].keys()))
        writer.writeheader()
        for row, _F in entries:
            writer.writerow(row)

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------
    _write_report(entries, bounds, runtime_total)

    print(f"\nTotal wall time: {runtime_total:.1f}s")
    print(f"CSV: {CSV_PATH}")
    print(f"Report: {MD_PATH}")
    return 0


def _write_report(entries, bounds, runtime_total: float) -> None:
    main_rows = [row for row, _ in entries if row["phase"] == "main"]
    sweep_rows = [row for row, _ in entries if row["phase"] == "sweep"]
    envelope_names = sorted({row["envelope"] for row in main_rows})
    methods_present = [m for m in METHOD_ORDER if any(r["method"] == m for r in main_rows)]

    lines: list[str] = []
    lines.append("# CareLoop optimiser benchmark — real dish dataset (214 dishes)")
    lines.append("")
    budget = os.environ.get("CARELOOP_BENCH_BUDGET", "evaluations")
    lines.append(
        f"Budget mode: **{budget}**. "
        + (f"Pymoo search limit: {os.environ.get('CARELOOP_BENCH_SECONDS', '0.5')} seconds per run. "
           if budget == "time" else "Pymoo search limit: population × nominal generations evaluations. ")
        + "Actual evaluation counts are recorded in the CSV. Nominal generations are not a stopping condition. "
        "Wall times include cold-start/compilation overhead and repair; these are not strict latency bounds. "
        "GA/greedy/random keep their native budgets."
    )
    lines.append("")
    lines.append(
        "Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by "
        "envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN "
        "floors / TARGETs are soft objective terms per PLAN.md module 4). "
        "HV = pymoo exact hypervolume "
        "on min-max normalised objectives (per-envelope bounds across all "
        "methods — guaranteed and raw — ref point 1.1^4). Rows labelled "
        "`<method>-raw` run the same pymoo algorithm with `guarantee=False` "
        "and report their honest hard-constraint violation rate; guaranteed "
        "rows carry the repair/greedy feasibility guarantee (violation rate 0 "
        "by construction, modulo explicit infeasibility diagnoses). "
        "ga / greedy / random are inherently raw baselines."
    )
    lines.append("")
    lines.append(
        "Algorithm configuration (4 objectives, pop=40, gen=80): "
        "**NSGA-III** das-dennis p=4 (35 reference directions), same "
        "IntegerRandomSampling + SBX + PM operators as NSGA-II; **MOEA/D** the "
        "same 35 weight vectors, T=15 neighbours, PBI decomposition (theta=5), "
        "neighbour mating p=0.9, population tied to the weight-vector count "
        "(35), unconstrained formulation (pymoo's MOEA/D cannot encode "
        "constraints — the guarantee wrapper still fences the reported plan); "
        "**AGE-MOEA** geometry-adaptive survival (numba), same operators; "
        "**SMSEMOA** exact hypervolume-contribution survival, pop=40 to bound "
        "the 4-D HV cost. RNSGA-II skipped: reference points need per-envelope "
        "calibration in raw objective units; SMSEMOA already covers the "
        "indicator-based corner."
    )
    lines.append("")

    # Headline summary per method
    lines.append("## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)")
    lines.append("")
    lines.append(
        "| method | guarantee | mean HV | HV std | violation rate | mean runtime (ms) |"
    )
    lines.append("|---|---|---|---|---|---|")
    for method in methods_present:
        rs = [r for r in main_rows if r["method"] == method]
        hvs = [float(r["hypervolume"]) for r in rs]
        viol_rate = sum(1 for r in rs if r["feasible"] == 0) / len(rs) if rs else 0.0
        guar = "yes" if _is_guaranteed(method) else "no"
        lines.append(
            f"| {method} | {guar} | {_mean(hvs):.4f} | {_std(hvs):.4f} | {viol_rate:.0%} "
            f"| {_mean([r['runtime_ms'] for r in rs]):.1f} |"
        )
    lines.append("")

    # Per-envelope x method mean HV
    lines.append("## Mean hypervolume per envelope")
    lines.append("")
    lines.append("| envelope | " + " | ".join(methods_present) + " |")
    lines.append("|---" * (len(methods_present) + 1) + "|")
    for env_name in envelope_names:
        cells = []
        for method in methods_present:
            hvs = [
                float(r["hypervolume"])
                for r in main_rows
                if r["envelope"] == env_name and r["method"] == method
            ]
            cells.append(f"{_mean(hvs):.4f}")
        lines.append(f"| {env_name} | " + " | ".join(cells) + " |")
    lines.append("")

    # Sweep table
    if sweep_rows:
        lines.append("## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)")
        lines.append("")
        lines.append("| pop | gen | mean HV | mean runtime (ms) |")
        lines.append("|---|---|---|---|")
        for pop_size in SWEEP_POP:
            for n_gen in SWEEP_GEN:
                rs = [
                    r
                    for r in sweep_rows
                    if r["pop_size"] == pop_size and r["n_gen"] == n_gen
                ]
                lines.append(
                    f"| {pop_size} | {n_gen} | {_mean([float(r['hypervolume']) for r in rs]):.4f} "
                    f"| {_mean([r['runtime_ms'] for r in rs]):.1f} |"
                )
        lines.append("")

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------
    lines.append("## Recommendation")
    lines.append("")

    if sweep_rows:
        sweep_stats = []
        for pop_size in SWEEP_POP:
            for n_gen in SWEEP_GEN:
                rs = [
                    r for r in sweep_rows
                    if r["pop_size"] == pop_size and r["n_gen"] == n_gen
                ]
                sweep_stats.append(
                    {
                        "pop": pop_size,
                        "gen": n_gen,
                        "hv": _mean([float(r["hypervolume"]) for r in rs]),
                        "ms": _mean([r["runtime_ms"] for r in rs]),
                    }
                )
        fastest = min(sweep_stats, key=lambda s: s["ms"])
        best_hv = max(s["hv"] for s in sweep_stats)
        knee_candidates = [
            s for s in sweep_stats
            if s["hv"] >= best_hv - 0.02 * max(best_hv, 1e-9)
        ]
        knee = min(knee_candidates, key=lambda s: s["ms"])
        lines.append(
            f"* Fastest swept NSGA-II config: pop={fastest['pop']}, gen={fastest['gen']} "
            f"(mean HV {fastest['hv']:.4f}, {fastest['ms']:.0f} ms/solve)."
        )
        lines.append(
            f"* NSGA-II knee point (HV within 2% of the best {best_hv:.4f}): "
            f"**pop={knee['pop']}, gen={knee['gen']}** "
            f"(mean HV {knee['hv']:.4f}, {knee['ms']:.0f} ms/solve)."
        )

    # Algorithm choice across the guaranteed comparison set.
    def _stats(method: str) -> dict:
        rs = [r for r in main_rows if r["method"] == method]
        return {
            "method": method,
            "hv": _mean([float(r["hypervolume"]) for r in rs]),
            "ms": _mean([r["runtime_ms"] for r in rs]),
            "viol": sum(1 for r in rs if r["feasible"] == 0) / len(rs) if rs else 0.0,
        }

    guar_stats = [_stats(m) for m in PYMOO_METHODS if m in methods_present]
    raw_stats = [_stats(m) for m in methods_present if m.endswith("-raw") or m in ("ga", "greedy", "random")]
    best_guar = max(guar_stats, key=lambda s: s["hv"]) if guar_stats else None
    best_raw = max(raw_stats, key=lambda s: s["hv"]) if raw_stats else None
    fastest_guar = min(guar_stats, key=lambda s: s["ms"]) if guar_stats else None

    if best_guar:
        nsga2_stat = next((s for s in guar_stats if s["method"] == "nsga2"), None)
        gap = (
            (nsga2_stat["hv"] - best_guar["hv"]) / max(best_guar["hv"], 1e-9)
            if nsga2_stat and best_guar["hv"] > 0 else 0.0
        )
        lines.append(
            f"* Best guaranteed method by mean HV: **{best_guar['method']}** "
            f"(HV {best_guar['hv']:.4f}, {best_guar['ms']:.0f} ms/solve); "
            f"NSGA-II scores {nsga2_stat['hv']:.4f} at {nsga2_stat['ms']:.0f} ms/solve."
            if nsga2_stat else
            f"* Best guaranteed method by mean HV: **{best_guar['method']}** "
            f"(HV {best_guar['hv']:.4f}, {best_guar['ms']:.0f} ms/solve)."
        )
        if best_raw:
            lines.append(
                f"* Best raw method by mean HV: {best_raw['method']} "
                f"(HV {best_raw['hv']:.4f}, violation rate {best_raw['viol']:.0%}) — "
                "raw and guaranteed HV figures are directly comparable: HV is "
                "computed only over feasible front members (infeasible front "
                "members are filtered out before the HV calculation), so raw "
                "HV is not inflated by infeasible members. Raw rows differ in "
                "that they report honest hard-constraint violation rates and "
                "skip the repair step that guarantees the delivered plan."
            )
        # Recommendation text: keep the production NSGA-II path unless a
        # challenger wins on HV at a comparable runtime AND stays guaranteed.
        if best_guar["method"] != "nsga2" and best_guar["hv"] > (nsga2_stat["hv"] if nsga2_stat else 0.0):
            ratio = best_guar["ms"] / max(nsga2_stat["ms"], 1e-9) if nsga2_stat else float("inf")
            lines.append(
                f"* **Algorithm recommendation: {best_guar['method']}** — highest mean HV "
                f"among guarantee-carrying methods ({best_guar['hv']:.4f} vs NSGA-II "
                f"{nsga2_stat['hv']:.4f}) at {ratio:.1f}x the NSGA-II runtime; it would be "
                "a drop-in ``method=`` argument to ``solve()`` (the guarantee "
                "path is method-agnostic)."
            )
        else:
            lines.append(
                "* **Algorithm recommendation: keep NSGA-II as the production "
                "method.** No guarantee-carrying challenger beats its HV at a "
                "better runtime, and NSGA-II is the only path with the "
                "battle-tested fallback-GA engine for pymoo-less environments."
            )
        if fastest_guar and fastest_guar["method"] != best_guar["method"]:
            lines.append(
                f"* Budget option: {fastest_guar['method']} is the cheapest "
                f"guaranteed method ({fastest_guar['ms']:.0f} ms/solve, HV "
                f"{fastest_guar['hv']:.4f}) if latency ever trumps front quality."
            )
        lines.append(
            "* The guarantee wrapper (repair + greedy fallback) is "
            "method-agnostic: every guaranteed row reports violation rate 0% "
            "regardless of algorithm, so algorithm choice affects front "
            "quality and runtime only."
        )
    lines.append(
        "* Interpretation caveat: the HV metric scores the whole Pareto front "
        "(front coverage), not the single delivered plan. Single-point "
        "baselines (GA scalarisation, greedy) are structurally disadvantaged "
        "on full-front HV because they emit one plan per solve; the quality of "
        "that single delivered meal plan answers a different question and is "
        "assessed separately by the constraint-satisfaction evaluation."
    )
    lines.append(
        "* Work budgets: pymoo methods use actual-evaluation termination "
        "(population × generations evaluations by default); counts are recorded "
        "from algorithm.evaluator.n_eval in the CSV. Generation-boundary overshoot "
        "is possible. CARELOOP_BENCH_BUDGET=time selects wall-time termination "
        "with CARELOOP_BENCH_SECONDS (default 0.5). GA/greedy/random retain their "
        "native budgets and are not claimed to have equal work. Repair/evaluation "
        "outside pymoo is excluded from the search count but included in runtime."
    )
    lines.append(
        f"* Total harness wall time: {runtime_total:.0f}s"
        + (" (SMOKE run — not comparable to the full benchmark)" if SMOKE else "")
        + ". Baselines: GA scalarises (single-point fronts -> lower HV); greedy is "
        "feasibility-aware by construction and near-instant but myopic; random "
        "is the floor on quality. Under the module-4 encoding (hard = MAX "
        "ceilings + exclusions only) raw methods rarely violate a ceiling on "
        "these envelopes, so methods are separated mainly by hypervolume; the "
        "repair/greedy guarantee remains the backstop for genuinely tight "
        "ceilings."
    )
    lines.append("")

    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
