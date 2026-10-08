"""Q6 — Objective/selection ablation, meal-composition ablation, exact reference.

Milestone 2 objective-selection comparison (
§5 "Run the objective/selection ablation, followed by the meal-composition
ablation" and "Add a small exact feasibility/quality reference").

Phase 1 — selection ablation (paired design)
--------------------------------------------
For every eligible patient (rule status != REJECTED) and 3 paired seeds
(:data:`SEEDS` = (42, 43, 44), fixed constants) the SAME NSGA-II front
(``solve(..., method="nsga2", pop_size=40, n_gen=80)``; the solver requires an
APPROVED envelope, so a content-unchanged APPROVED copy is built here — no app
store is touched) is scored by the three selection strategies from
``backend.optim.selection``:

* ``scalar_selection``     — status quo (raw-unit ``SCALAR_WEIGHTS``);
* ``normalised_selection`` — per-nutrient relative deviation vs the aims;
* ``adequacy_first_selection`` — lexicographic worst-day shortfall first.

Every strategy is scored against the ORIGINAL approved envelope (never a
MIN-relaxed copy — floors are soft under the PLAN.md module-4 encoding, so the
plain approved envelope is solved directly).  Per selected plan we report, as
pure functions over ``daily_totals`` (adequacy semantics mirror
``backend/app/core/plan_service.py``: one entry per MIN/TARGET aim, MAX
ceilings excluded, worst day = lowest daily total, met day = total >= aim):

* per-nutrient mean daily shortfall, worst-day relative shortfall %,
  met-days fraction;
* hard feasibility (``problem.evaluate`` violations == 0), cost, variety,
  preference fit, deviation, scalar score, front size, solver runtime.

Phase 2 — meal-composition ablation (bounded, informational)
------------------------------------------------------------
The production encoding (1 dish per slot) is NOT changed.  A compact GA
searches a 2-dish encoding: each of the 21 slots holds exactly 2 dishes, a
MAIN (allowed pool minus categories ``drink``/``dessert``/``kopitiam``) and a
SIDE (allowed pool with category in ``soup``/``healthy``/``cai_png`` or the
``vegetable`` tag), with no dish id twice within the same day.  Operators
(documented for the review's representation-ablation protocol): tournament
selection (k=3) on the scalar score, uniform slot-swap crossover (per slot the
whole (main, side) pair swaps with p=0.5), slot-resample mutation (1-3 random
slots; main and/or side index resampled uniformly), 2-scalar-elitism, and the
repair pattern of rejecting infeasible offspring (an infeasible offspring is
replaced by a feasible parent, so the population stays feasible).  The
evaluator (:class:`CompositionEvaluator`) is a VECTORIZED numpy mirror of
``problem.evaluate`` for multi-dish slots (same objectives, same EPS
tolerance, same daily+horizon MAX ordering) — cross-checked against
``problem.evaluate`` in ``evaluation/test_ablation.py``.  The final front is
the deduplicated set of feasible individuals encountered during the run.  The
same three selections are applied to that front.

Run on a bounded subset (first 8 eligible patients, 1 seed) and reported
informationally: the 2-dish encoding doubles dishes per day (6 vs 3), and the
category/eligibility sets are heuristic annotations over an UNVERIFIED
dataset (214/214 dishes unverified per the data audit), so no pass/fail is
assigned to this phase.

Phase 3 — exact-reference quality reporting (informational)
-----------------------------------------------------------
For each patient (scalar-selected plan of the first seed):
``exact_reference.plan_vs_exact`` gives per-additive-objective daily gaps vs
the exact one-day optimum, the 7-day lower bounds, and whether the delivered
plan hits the per-day additive optimum (gap <= 1e-6).  Solver
``infeasibility_status`` outcomes are counted across the suite.  Review-
mandated disclosure: variety is excluded from the exact reference (not
per-day decomposable); the exact baseline is NOT an optimum for all four
objectives.

Verdict (derived, never hardcoded)
----------------------------------
The selection ablation is PASS iff ALL of:

1. at least one comparable (patient, seed) row exists for BOTH
   ``scalar_selection`` and ``adequacy_first_selection``;
2. every adequacy-first-selected plan is hard-feasible
   (``feasibility_rate == 1.0``);
3. adequacy-first's pooled mean worst-day relative shortfall is STRICTLY
   lower than scalar selection's;
4. adequacy-first's pooled mean cost is at most 10% above scalar selection's
   (:data:`_COST_CAP`).

Any failed condition fails the verdict and is named in ``verdict_note``
(review protocol point 7 — failed expectations affect the verdict, they do
not live in an informational section).  The composition ablation and the
exact-reference section are informational by design (heuristic data
annotations; bounds that are not 4-objective optima).
"""

from __future__ import annotations

import random
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from evaluation.common import load_patients
from rules.engine import run_rules

from backend.optim.problem import (  # noqa: E402
    EPS,
    MEALS_PER_DAY,
    OBJECTIVE_NAMES,
    SCALAR_WEIGHTS,
    TAG_PREFERENCE,
    ConstraintKind,
    allowed_dishes,
    daily_totals,
    evaluate,
    scalar_score,
)
from backend.optim.selection import (  # noqa: E402
    adequacy_first_selection,
    normalised_selection,
    scalar_selection,
)
from backend.optim.toy_data import NUTRIENT_KEYS, Dish  # noqa: E402

__all__ = [
    "evaluate_q6",
    "evaluate_selection_ablation",
    "evaluate_composition_ablation",
    "evaluate_exact_reference",
    "adequacy_rows",
    "plan_metrics",
    "derive_selection_verdict",
    "CompositionEvaluator",
    "composition_ga",
    "SEEDS",
]

# Fixed paired seeds (review protocol: paired patient/seed runs; the same
# front is reused by all three strategies, so comparisons are paired).
SEEDS: tuple[int, ...] = (42, 43, 44)

_EPS = 1e-9            # mirrors plan_service / selection epsilon
_OPTIMUM_GAP_TOL = 1e-6  # "hits the per-day additive optimum" gap tolerance
_COST_CAP = 0.10       # verdict condition 4: pooled mean cost increase <= 10%

STRATEGY_NAMES: tuple[str, ...] = ("scalar", "normalised", "adequacy_first")
_STRATEGIES = {
    "scalar": scalar_selection,
    "normalised": normalised_selection,
    "adequacy_first": adequacy_first_selection,
}

# Composition encoding eligibility sets (heuristic annotations; verified
# non-empty against data/dishes.json: categories drink 20, dessert 7,
# kopitiam 28, soup 19, healthy 18, cai_png 28, tag "vegetable" 3).
MAIN_EXCLUDED_CATEGORIES = frozenset({"drink", "dessert", "kopitiam"})
SIDE_CATEGORIES = frozenset({"soup", "healthy", "cai_png"})
SIDE_TAG = "vegetable"

_FIXED_APPROVAL_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)

_COMPOSITION_NOTE = (
    "Controlled encoding ablation; production now uses optional-side adequacy search. "
    "The 2-dish encoding doubles dishes per day (6 vs 3), so cost, preference "
    "sums and per-day nutrient totals are NOT directly comparable to the "
    "1-dish encoding. Meal-role eligibility (MAIN/SIDE sets in config) and "
    "the per-day repetition limit are heuristic annotations over an "
    "UNVERIFIED dataset (214/214 dishes unverified), not verified data. No pass/fail is assigned "
    "to this phase."
)

_EXACT_DISCLOSURE = (
    "Variety is excluded from the exact reference (it is defined over the "
    "whole horizon and not per-day decomposable); the exact baseline covers "
    "nutrient_target_deviation, the raw preference sum and cost only and is "
    "NOT an optimum for all four objectives. preference_sum gaps measure "
    "distance above the raw-sum lower bound, not preference suboptimality "
    "(preference_fit negates the mean tag-preference sum)."
)


def _mean(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _approve(envelope_model: Any) -> Any:
    """Simulate the clinician approval gate (content unchanged, status flipped).

    Mirrors ``evaluation.q_satisfaction._approve``; the solver requires
    EnvelopeStatus.APPROVED and no app store is touched.
    """
    return envelope_model.model_copy(update={
        "status": "APPROVED",
        "approved_by": "evaluation-suite (simulated clinician approval)",
        "approved_at": _FIXED_APPROVAL_TIME,
    })


# ---------------------------------------------------------------------------
# Adequacy metrics (pure functions over daily totals; plan_service semantics)
# ---------------------------------------------------------------------------
def adequacy_rows(daily: list[dict[str, float]], envelope: Any) -> list[dict[str, Any]]:
    """Per MIN/TARGET aim adequacy of daily totals vs the ORIGINAL aims.

    Semantics mirror ``backend/app/core/plan_service.py`` ``adequacy[]``:
    one entry per MIN/TARGET constraint in envelope order (MAX ceilings are
    excluded — ceiling compliance is a hard-feasibility matter); the worst
    day is the day with the LOWEST total; ``shortfall = aim - worst_daily``
    (negative when the worst day still exceeds the aim); the relative
    shortfall percentage is 0 when ``aim <= 0``; a day "meets" the aim when
    ``total >= aim - 1e-9`` (plan_service semantics; a TARGET aim is met from
    below — two-sided deviation is scored by the selection strategies).
    """
    rows: list[dict[str, Any]] = []
    for constraint in envelope.targets:
        kind = constraint.kind.value
        if kind == "max":
            continue
        key = constraint.nutrient.value
        aim = float(constraint.value)
        series = [day[key] for day in daily]
        if not series:
            continue
        gaps = [abs(aim - value) if kind == "target" else max(0., aim - value) for value in series]
        shortfall = max(gaps)
        rows.append({
            "nutrient": key,
            "kind": kind,
            "aim": aim,
            "mean_daily_shortfall": sum(gaps) / len(series),
            "worst_day_rel_shortfall_pct": (
                shortfall / aim * 100.0 if aim > _EPS else 0.0
            ),
            "met_days_fraction": (
                sum(1 for gap in gaps if gap <= _EPS) / len(series)
            ),
        })
    return rows


def plan_metrics(plan: list[list[str]], envelope: Any, dishes: list[Dish]) -> dict[str, Any]:
    """Canonical metrics for one selected plan vs the ORIGINAL approved aims.

    Hard feasibility is recomputed with the canonical ``problem.evaluate``
    (violations == 0); adequacy comes from :func:`adequacy_rows` over
    ``daily_totals``.
    """
    objectives, violations = evaluate(plan, envelope, dishes)
    daily = daily_totals(plan, dishes)
    rows = adequacy_rows(daily, envelope)
    return {
        "hard_feasible": not violations,
        "violation_count": len(violations),
        "worst_day_rel_shortfall_pct": max(
            (r["worst_day_rel_shortfall_pct"] for r in rows), default=0.0
        ),
        "mean_daily_shortfall": _mean([r["mean_daily_shortfall"] for r in rows]) or 0.0,
        "mean_met_days_fraction": _mean([r["met_days_fraction"] for r in rows]),
        "scalar_score": scalar_score(objectives),
        "nutrient_target_deviation": objectives["nutrient_target_deviation"],
        "preference_fit": objectives["preference_fit"],
        "variety": objectives["variety"],
        "cost": objectives["cost"],
        "adequacy": rows,
    }


_METRIC_FIELDS = (
    "worst_day_rel_shortfall_pct",
    "mean_daily_shortfall",
    "mean_met_days_fraction",
    "scalar_score",
    "nutrient_target_deviation",
    "preference_fit",
    "variety",
    "cost",
)


def _pool_strategy_metrics(strategy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled mean metrics over all (patient, seed) rows of one strategy."""
    out: dict[str, Any] = {
        "rows": len(strategy_rows),
        "feasibility_rate": (
            sum(1 for r in strategy_rows if r["hard_feasible"]) / len(strategy_rows)
            if strategy_rows else None
        ),
    }
    for field in _METRIC_FIELDS:
        key = field if field.startswith("mean_") else f"mean_{field}"
        out[key] = _mean([r.get(field) for r in strategy_rows])
    out["mean_front_size"] = _mean([r.get("front_size") for r in strategy_rows])
    # NOTE: no pooled runtime aggregate — per-row wall-clock `solver_runtime_s`
    # stays in the per-patient rows (runtimes are non-deterministic and are
    # excluded from the suite's determinism check).
    return out


# ---------------------------------------------------------------------------
# Phase 1 — selection ablation
# ---------------------------------------------------------------------------
def solve_guarded(envelope: Any, dishes: list[Dish], seed: int, pop_size: int,
                  n_gen: int) -> dict[str, Any]:
    """``solver.solve`` with the production NSGA-II configuration."""
    from backend.optim.solver import solve

    return solve(envelope, dishes, seed=seed, method="nsga2",
                 pop_size=pop_size, n_gen=n_gen)


def evaluate_selection_ablation(
    patients: list[dict[str, Any]],
    dishes: list[Dish],
    seeds: tuple[int, ...] = SEEDS,
    pop_size: int = 40,
    n_gen: int = 80,
) -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]]:
    """Run the paired selection ablation.

    Returns ``(summary, internals)``.  ``internals`` maps
    ``(patient_id, seed)`` to ``{"front": entries, "scalar_plan": plan,
    "infeasibility_status": str}`` for downstream phases (composition pairing
    and exact reference); it is intentionally NOT part of the serialised
    result.  ``summary`` carries pooled per-strategy metrics, per-patient
    rows (with per-nutrient adequacy) and paired deltas.
    """
    from shared.envelope_schema import NutrientEnvelope

    per_patient: list[dict[str, Any]] = []
    strategy_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in STRATEGY_NAMES}
    status_counts: Counter = Counter()
    internals: dict[tuple[str, int], dict[str, Any]] = {}
    rejected_ids: list[str] = []

    for patient in patients:
        engine_result = run_rules(patient)
        envelope_dict = engine_result["envelope"]
        if envelope_dict["status"] == "REJECTED":
            rejected_ids.append(envelope_dict["patient_id"])
            per_patient.append({
                "patient_id": envelope_dict["patient_id"],
                "archetype": patient.get("archetype"),
                "attempted": False,
                "note": "out-of-scope patient; no envelope to optimise",
            })
            continue

        approved = _approve(NutrientEnvelope(**envelope_dict))
        seed_rows: list[dict[str, Any]] = []
        for seed in seeds:
            started = time.perf_counter()
            result = solve_guarded(approved, dishes, seed=seed,
                                   pop_size=pop_size, n_gen=n_gen)
            runtime_s = time.perf_counter() - started
            status = result.get("infeasibility_status") or "none"
            status_counts[status] += 1
            front = list(result.get("front") or [])
            seed_row: dict[str, Any] = {
                "seed": seed,
                "front_size": len(front),
                "solver_runtime_s": round(runtime_s, 3),  # wall-clock, not deterministic
                "engine": result.get("engine"),
            }
            internals[(approved.patient_id, seed)] = {
                "front": front,
                "scalar_plan": list(result.get("plan") or []),
                "infeasibility_status": status,
            }
            if not front:
                seed_row["strategies"] = None
                seed_row["note"] = (
                    "no feasible front (solver diagnosis); no plan selected"
                )
            else:
                strategies: dict[str, dict[str, Any]] = {}
                for name, selector in _STRATEGIES.items():
                    entry = selector(front, approved, dishes)
                    metrics = plan_metrics(entry["plan"], approved, dishes)
                    metrics["front_size"] = len(front)
                    metrics["solver_runtime_s"] = round(runtime_s, 3)
                    strategies[name] = metrics
                    strategy_rows[name].append(metrics)
                seed_row["strategies"] = strategies
            seed_rows.append(seed_row)

        statuses = {
            internals[(approved.patient_id, seed)]["infeasibility_status"]
            for seed in seeds
        }
        per_patient.append({
            "patient_id": approved.patient_id,
            "archetype": patient.get("archetype"),
            "attempted": True,
            "infeasibility_status": (
                "none" if statuses == {"none"} else ", ".join(sorted(statuses))
            ),
            "seeds": seed_rows,
        })

    pooled = {name: _pool_strategy_metrics(rows) for name, rows in strategy_rows.items()}
    delta_rows = _paired_delta_rows(per_patient)
    summary = {
        "config": {
            "seeds": list(seeds),
            "pop_size": pop_size,
            "n_gen": n_gen,
            "method": "nsga2",
            "scored_against": (
                "ORIGINAL approved envelope (no MIN relaxation applied; MIN "
                "floors and TARGETs are soft under the PLAN.md module-4 "
                "encoding); all three selections score the SAME front"
            ),
            "strategies": {
                "scalar": "status-quo raw-unit scalar_score minimum",
                "normalised": "mean per-day per-nutrient relative deviation",
                "adequacy_first": (
                    "lexicographic worst-day relative shortfall, unmet count, "
                    "scalar_score"
                ),
            },
        },
        "eligible_patients": sum(1 for r in per_patient if r.get("attempted")),
        "rejected_patient_ids": rejected_ids,
        "solves": len(seeds) * sum(1 for r in per_patient if r.get("attempted")),
        "infeasibility_status_counts": dict(status_counts),
        "pooled": pooled,
        "paired_deltas": _aggregate_deltas(delta_rows),
        "delta_rows": delta_rows,
        "per_patient": per_patient,
    }
    return summary, internals


def _paired_delta_rows(per_patient: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-(patient, seed) paired deltas vs the scalar baseline."""
    rows: list[dict[str, Any]] = []
    for patient in per_patient:
        for seed_row in patient.get("seeds") or []:
            strategies = seed_row.get("strategies")
            if not strategies:
                continue
            base = strategies["scalar"]
            for name in ("normalised", "adequacy_first"):
                other = strategies[name]
                base_cost = base["cost"]
                rows.append({
                    "patient_id": patient["patient_id"],
                    "seed": seed_row["seed"],
                    "vs": name,
                    "delta_worst_day_rel_shortfall_pct":
                        other["worst_day_rel_shortfall_pct"]
                        - base["worst_day_rel_shortfall_pct"],
                    "delta_cost_pct": (
                        (other["cost"] - base_cost) / base_cost * 100.0
                        if base_cost and base_cost > _EPS else None
                    ),
                })
    return rows


def _aggregate_deltas(delta_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in ("normalised", "adequacy_first"):
        sub = [r for r in delta_rows if r["vs"] == name]
        dworst = [r["delta_worst_day_rel_shortfall_pct"] for r in sub]
        dcost = [r["delta_cost_pct"] for r in sub if r["delta_cost_pct"] is not None]
        out[name] = {
            "rows": len(sub),
            "mean_delta_worst_day_rel_shortfall_pct": _mean(dworst),
            "mean_delta_cost_pct": _mean(dcost),
            "improved": sum(1 for d in dworst if d < -1e-9),
            "tied": sum(1 for d in dworst if abs(d) <= 1e-9),
            "regressed": sum(1 for d in dworst if d > 1e-9),
        }
    return out


def per_patient_deltas(delta_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-patient mean paired deltas (compact table for the report)."""
    by_patient: dict[str, dict[str, list[float]]] = {}
    for row in delta_rows:
        bucket = by_patient.setdefault(row["patient_id"], {})
        bucket.setdefault(row["vs"], []).append(
            row["delta_worst_day_rel_shortfall_pct"]
        )
    out = []
    for patient_id in sorted(by_patient):
        entry: dict[str, Any] = {"patient_id": patient_id}
        for name in ("normalised", "adequacy_first"):
            entry[f"delta_{name}_pct"] = _mean(by_patient[patient_id].get(name))
        out.append(entry)
    return out


def derive_selection_verdict(
    pooled: dict[str, dict[str, Any]],
    cost_cap: float = _COST_CAP,
) -> tuple[str, Optional[str]]:
    """Derive the selection-ablation verdict from the pooled numbers.

    PASS iff (documented in the module docstring): comparable rows exist for
    both strategies, adequacy_first feasibility rate == 1.0, adequacy_first's
    pooled mean worst-day relative shortfall is STRICTLY below scalar's, and
    its pooled mean cost is at most ``cost_cap`` (10%) above scalar's.
    Every failed condition is named in the note (review protocol point 7).
    """
    adq = pooled.get("adequacy_first") or {}
    sc = pooled.get("scalar") or {}
    if not adq.get("rows") or not sc.get("rows"):
        return "FAIL", "no comparable selection rows (every front was empty)"
    failures: list[str] = []
    if adq.get("feasibility_rate") != 1.0:
        failures.append(
            f"adequacy_first feasibility rate {adq.get('feasibility_rate')!r} != 1.0"
        )
    delta = (adq.get("mean_worst_day_rel_shortfall_pct") or 0.0) - (
        sc.get("mean_worst_day_rel_shortfall_pct") or 0.0
    )
    if not delta < 0:
        failures.append(
            "pooled mean worst-day relative shortfall not strictly reduced "
            f"(delta {delta:.4f} pct-points vs scalar)"
        )
    sc_cost = sc.get("mean_cost") or 0.0
    adq_cost = adq.get("mean_cost") or 0.0
    if sc_cost > _EPS and adq_cost > sc_cost * (1.0 + cost_cap):
        failures.append(
            f"pooled mean cost increase {(adq_cost / sc_cost - 1.0) * 100:.1f}% "
            f"exceeds the {cost_cap * 100:.0f}% cap"
        )
    if failures:
        return "FAIL", "; ".join(failures)
    return "PASS", None


# ---------------------------------------------------------------------------
# Phase 2 — meal-composition ablation (2-dish main + side encoding)
# ---------------------------------------------------------------------------
class CompositionEvaluator:
    """Vectorised numpy evaluator for the 2-dish (main + side) encoding.

    Mirrors ``problem.evaluate`` semantics for multi-dish slots: identical
    objective definitions (deviation / preference_fit / variety / cost, all
    minimised, in :data:`OBJECTIVE_NAMES` order), identical EPS tolerance and
    the same canonical daily + horizon MAX constraint ordering — verified
    against ``problem.evaluate`` in ``evaluation/test_ablation.py``.  On top
    of the PLAN.md module-4 hard constraints it enforces the composition
    encoding's own repetition limit (no dish id twice within the same day),
    reported separately in :meth:`eval_batch` (it is NOT part of
    ``problem.evaluate``).

    Individuals are ``np.ndarray`` of shape ``(n_days * 3, 2)``: column 0
    indexes the MAIN pool, column 1 the SIDE pool.
    """

    def __init__(self, envelope: Any, dishes: list[Dish], n_days: int = 7):
        self.envelope = envelope
        self.dishes = dishes
        self.n_days = n_days
        self.slots = n_days * MEALS_PER_DAY

        pool = allowed_dishes(envelope, dishes)
        mains = [d for d in pool if d.category not in MAIN_EXCLUDED_CATEGORIES]
        sides = [
            d for d in pool
            if d.category in SIDE_CATEGORIES or SIDE_TAG in d.tags
        ]
        self.fallback_used = False
        if not mains:  # documented widening: never silently drop the phase
            mains = list(pool)
            self.fallback_used = True
        if not sides:
            sides = (
                [d for d in pool if d.category not in MAIN_EXCLUDED_CATEGORIES]
                or list(pool)
            )
            self.fallback_used = True

        self.main_pool: list[Dish] = mains
        self.side_pool: list[Dish] = sides
        self.size_m = len(mains)
        self.size_s = len(sides)

        # Global dish-id positions (unique per dish_id across the full pool)
        # drive the variety objective and the repetition check — a dish can be
        # eligible as both MAIN and SIDE and must count as the same dish.
        gpos = {d.dish_id: i for i, d in enumerate(dishes)}
        self.gid_m = np.array([gpos[d.dish_id] for d in mains], dtype=int)
        self.gid_s = np.array([gpos[d.dish_id] for d in sides], dtype=int)
        self.full_size = len(dishes)  # problem._obj_variety denominator base

        self.nut_m = np.array(
            [[d.nutrient(k) for k in NUTRIENT_KEYS] for d in mains], dtype=float
        ).reshape(max(self.size_m, 1), len(NUTRIENT_KEYS))
        self.nut_s = np.array(
            [[d.nutrient(k) for k in NUTRIENT_KEYS] for d in sides], dtype=float
        ).reshape(max(self.size_s, 1), len(NUTRIENT_KEYS))

        self.pref_m = np.array(
            [sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in mains],
            dtype=float,
        )
        self.pref_s = np.array(
            [sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in sides],
            dtype=float,
        )
        self.price_m = np.array([d.price_sgd for d in mains], dtype=float)
        self.price_s = np.array([d.price_sgd for d in sides], dtype=float)

        col = {k: i for i, k in enumerate(NUTRIENT_KEYS)}
        self.targets = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets if c.kind == ConstraintKind.TARGET
        ]
        self.max_daily = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets if c.kind == ConstraintKind.MAX
        ]
        self.min_daily = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets if c.kind == ConstraintKind.MIN
        ]
        self.n_constraints = len(self.max_daily) * (n_days + 1)

    # -- decoding ----------------------------------------------------------
    def to_plan(self, individual: np.ndarray) -> list[list[str]]:
        """Decode an index individual into a 21-slot, 2-dish-per-slot plan."""
        ind = np.asarray(individual, dtype=int)
        return [
            [self.main_pool[ind[s, 0]].dish_id, self.side_pool[ind[s, 1]].dish_id]
            for s in range(self.slots)
        ]

    def plan_to_individual(self, plan: list[list[str]]) -> np.ndarray:
        """Encode a 2-dish plan; raises ValueError on role/pool violations."""
        if len(plan) != self.slots or any(len(slot) != 2 for slot in plan):
            raise ValueError(
                f"expected {self.slots} slots of exactly 2 dishes (main, side)"
            )
        main_pos = {d.dish_id: i for i, d in enumerate(self.main_pool)}
        side_pos = {d.dish_id: i for i, d in enumerate(self.side_pool)}
        ind = np.zeros((self.slots, 2), dtype=int)
        for s, (main_id, side_id) in enumerate(plan):
            if main_id not in main_pos:
                raise ValueError(f"{main_id!r} is not in the MAIN pool")
            if side_id not in side_pos:
                raise ValueError(f"{side_id!r} is not in the SIDE pool")
            ind[s, 0], ind[s, 1] = main_pos[main_id], side_pos[side_id]
        return ind

    # -- batch evaluation ---------------------------------------------------
    def eval_batch(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Evaluate a batch ``(P, slots, 2)``.

        Returns ``(F, G, repetition)``: ``F`` (P, 4) mirrors
        ``problem.evaluate`` objectives in OBJECTIVE_NAMES order; ``G`` (P,
        n_constraints) is the canonical shifted MAX violation vector
        (``G <= 0`` == satisfied, EPS tolerance identical to
        ``FastEvaluator.g_vector``); ``repetition`` (P,) bool flags the
        composition encoding's per-day repetition limit.
        """
        X = np.asarray(X, dtype=int)
        if X.ndim != 3 or X.shape[1:] != (self.slots, 2):
            raise ValueError(f"expected shape (P, {self.slots}, 2), got {X.shape}")
        P = X.shape[0]
        K = len(NUTRIENT_KEYS)

        slot_nut = self.nut_m[X[:, :, 0]] + self.nut_s[X[:, :, 1]]  # (P, slots, K)
        daily = slot_nut.reshape(P, self.n_days, MEALS_PER_DAY, K).sum(axis=2)

        F = np.zeros((P, len(OBJECTIVE_NAMES)))

        # 1. nutrient_target_deviation (mean over days; same terms as problem)
        dev = np.zeros(P)
        for _col, value in self.targets:
            dev += np.abs(daily[:, :, _col] - value).sum(axis=1)
        for _col, value in self.min_daily:
            dev += np.maximum(0.0, value - daily[:, :, _col]).sum(axis=1)
        for _col, value in self.max_daily:
            dev += np.maximum(0.0, daily[:, :, _col] - value).sum(axis=1)
        F[:, 0] = dev / self.n_days if self.n_days else 0.0

        n_dishes = 2 * self.slots
        # 2. preference_fit: -mean tag-preference over all 2*slots dishes
        pref_total = (
            self.pref_m[X[:, :, 0]].sum(axis=1)
            + self.pref_s[X[:, :, 1]].sum(axis=1)
        )
        F[:, 1] = -pref_total / n_dishes if n_dishes else 0.0

        # 3. variety over global dish ids (identical formula to problem)
        gids = np.concatenate(
            [self.gid_m[X[:, :, 0]][:, :, None],
             self.gid_s[X[:, :, 1]][:, :, None]], axis=2
        )  # (P, slots, 2)
        flat = gids.reshape(P, n_dishes)
        offsets = flat + np.arange(P)[:, None] * self.full_size
        counts = np.bincount(
            offsets.ravel(), minlength=P * self.full_size
        ).reshape(P, self.full_size).astype(float)
        distinct = (counts > 0).sum(axis=1).astype(float)
        entropy = np.zeros(P)
        rows_with = np.flatnonzero(distinct > 0)
        if rows_with.size:
            probs = counts[rows_with] / n_dishes
            ent = -(
                probs * np.where(probs > 0, np.log(np.where(probs > 0, probs, 1.0)), 0.0)
            ).sum(axis=1)
            entropy[rows_with] = ent
        denom = np.log(self.full_size) if self.full_size > 1 else 1.0
        norm_entropy = np.minimum(1.0, entropy / denom) if denom > 0 else entropy
        distinct_ratio = distinct / min(self.full_size, n_dishes) if n_dishes else distinct
        F[:, 2] = -(0.5 * norm_entropy + 0.5 * distinct_ratio)

        # 4. cost
        F[:, 3] = (
            self.price_m[X[:, :, 0]].sum(axis=1)
            + self.price_s[X[:, :, 1]].sum(axis=1)
        )

        # Hard MAX constraints (daily + horizon), shifted by -EPS so
        # G <= 0 matches problem.evaluate's EPS tolerance.
        parts: list[np.ndarray] = []
        for _col, limit in self.max_daily:
            parts.append(np.maximum(0.0, daily[:, :, _col] - limit) - EPS)
            horizon = np.maximum(
                0.0, daily[:, :, _col].sum(axis=1) - limit * self.n_days
            ) - EPS
            parts.append(horizon[:, None])
        G = np.concatenate(parts, axis=1) if parts else np.zeros((P, 0))

        # Composition repetition limit: no dish id twice within the same day.
        day_gids = gids.reshape(P, self.n_days, 2 * MEALS_PER_DAY)
        sorted_day = np.sort(day_gids, axis=2)
        repetition = (sorted_day[:, :, 1:] == sorted_day[:, :, :-1]).any(axis=2).any(axis=1)
        return F, G, repetition

    def eval_single(self, individual: np.ndarray) -> tuple[np.ndarray, np.ndarray, bool]:
        F, G, rep = self.eval_batch(np.asarray(individual, dtype=int)[None])
        return F[0], G[0], bool(rep[0])

    def is_feasible_individual(self, individual: np.ndarray) -> bool:
        _F, G, rep = self.eval_single(individual)
        return bool((G <= 0).all()) and not rep


def _greedy_individual(ev: CompositionEvaluator, rng: random.Random,
                       tries: int = 40) -> Optional[np.ndarray]:
    """Build a full 7-day individual one feasible day at a time.

    Days are independent (every hard constraint is per-day), so a plan exists
    iff a feasible day exists.  Candidates are scored by the projected
    whole-day MAX violation magnitude after adding them, tie-broken by the
    candidate's own worst-constraint contribution and a seeded random jitter
    for diversity.  Returns ``None`` when no feasible day can be constructed
    within ``tries`` randomised greedy attempts.
    """
    main_pos = {int(g): i for i, g in enumerate(ev.gid_m)}
    side_pos = {int(g): i for i, g in enumerate(ev.gid_s)}
    for _attempt in range(tries):
        ind = np.zeros((ev.slots, 2), dtype=int)
        ok = True
        for day in range(ev.n_days):
            used: set[int] = set()  # repetition limit is per DAY
            day_nut = np.zeros((2 * MEALS_PER_DAY, len(NUTRIENT_KEYS)))
            picks: list[tuple[int, int]] = []
            for pos in range(2 * MEALS_PER_DAY):
                is_main = pos % 2 == 0
                pool_nut = ev.nut_m if is_main else ev.nut_s
                pool_gid = ev.gid_m if is_main else ev.gid_s
                pool_size = ev.size_m if is_main else ev.size_s
                best: Optional[int] = None
                best_key: Optional[tuple] = None
                for cand in range(pool_size):
                    if int(pool_gid[cand]) in used:
                        continue
                    totals = day_nut[:pos].sum(axis=0) + pool_nut[cand]
                    mag = sum(
                        max(0.0, totals[col] - limit)
                        for col, limit in ev.max_daily
                    )
                    worst_contrib = max(
                        (pool_nut[cand][col] for col, _ in ev.max_daily),
                        default=0.0,
                    )
                    key = (round(mag, 9), round(worst_contrib, 9),
                           rng.random() * 1e-6, cand)
                    if best_key is None or key < best_key:
                        best_key, best = key, cand
                if best is None:
                    ok = False
                    break
                day_nut[pos] = pool_nut[best]
                used.add(int(pool_gid[best]))
                picks.append((int(pool_gid[best]), best))
            if not ok:
                break
            final = day_nut.sum(axis=0)
            if any(final[col] > limit + EPS for col, limit in ev.max_daily):
                ok = False
                break
            for slot in range(MEALS_PER_DAY):
                ind[day * MEALS_PER_DAY + slot, 0] = main_pos[picks[slot * 2][0]]
                ind[day * MEALS_PER_DAY + slot, 1] = side_pos[picks[slot * 2 + 1][0]]
        if ok and ev.is_feasible_individual(ind):
            return ind
    return None


def _repair_individual(ev: CompositionEvaluator, individual: np.ndarray,
                       max_iters: int = 200) -> Optional[np.ndarray]:
    """Local-search repair: replace one dish at a time on the worst day.

    For the most-violated day the search tries every single-dish replacement
    (main slots draw from the MAIN pool, side slots from the SIDE pool, never
    duplicating a global dish id within the day) and takes the replacement
    minimising the day's total MAX violation magnitude.  Returns ``None``
    after ``max_iters`` iterations without reaching feasibility.
    """
    ind = np.asarray(individual, dtype=int).copy()
    K = len(NUTRIENT_KEYS)
    for _iteration in range(max_iters):
        _F, G, rep = ev.eval_single(ind)
        if (G <= 0).all() and not rep:
            return ind
        slot_nut = ev.nut_m[ind[:, 0]] + ev.nut_s[ind[:, 1]]
        daily = slot_nut.reshape(ev.n_days, MEALS_PER_DAY, K).sum(axis=1)
        over = np.zeros(ev.n_days)
        for col, limit in ev.max_daily:
            over = np.maximum(over, daily[:, col] - limit)
        day = int(np.argmax(over))
        if rep:
            # fix a duplicate first: swap one offending dish for the
            # lowest-contribution unused candidate in the same pool
            gids = np.concatenate(
                [ev.gid_m[ind[:, 0]], ev.gid_s[ind[:, 1]]], axis=1
            ).reshape(ev.n_days, MEALS_PER_DAY, 2)
            flat = gids[day].reshape(-1)
            dup_id = int(flat[np.flatnonzero(
                np.bincount(flat, minlength=ev.full_size) > 1
            )[0]])
            pos = int(np.flatnonzero(flat == dup_id)[-1])
            is_main = pos % 2 == 0
            nut = ev.nut_m if is_main else ev.nut_s
            gid = ev.gid_m if is_main else ev.gid_s
            allowed_ids = set(flat.tolist()) - {dup_id}
            contribution = nut[:, [col for col, _ in ev.max_daily]].sum(axis=1)
            for cand in np.argsort(contribution, kind="stable"):
                if int(gid[cand]) not in allowed_ids:
                    ind[day * MEALS_PER_DAY + pos // 2, 0 if is_main else 1] = int(cand)
                    break
            continue
        # single-dish replacement search on the most-violated day
        day_slice = slice(day * MEALS_PER_DAY, (day + 1) * MEALS_PER_DAY)
        day_nut = slot_nut[day_slice]
        limits = np.array([limit for _, limit in ev.max_daily])
        cols = [col for col, _ in ev.max_daily]
        best: Optional[tuple] = None
        for pos in range(2 * MEALS_PER_DAY):
            is_main = pos % 2 == 0
            nut = ev.nut_m if is_main else ev.nut_s
            gid = ev.gid_m if is_main else ev.gid_s
            used_ids = set(
                np.concatenate([ev.gid_m[ind[day_slice, 0]],
                                ev.gid_s[ind[day_slice, 1]]]).tolist()
            )
            totals = (day_nut.sum(axis=0) - day_nut[pos] + nut)[:, cols]
            mag = np.maximum(0.0, totals - limits).sum(axis=1)
            for cand in np.argsort(mag, kind="stable"):
                if int(gid[cand]) in used_ids:
                    continue
                key = (float(mag[cand]), int(cand), pos)
                if best is None or key < (best[0], best[1], best[2]):
                    best = key
                break
        if best is None:
            return None
        _mag, cand, pos = best
        ind[day * MEALS_PER_DAY + pos // 2, 0 if pos % 2 == 0 else 1] = cand
    return None


def composition_ga(
    ev: CompositionEvaluator,
    seed: int = 42,
    pop_size: int = 40,
    n_gen: int = 60,
    tournament_k: int = 3,
    repair_iters: int = 200,
) -> dict[str, Any]:
    """Compact GA over the 2-dish encoding (operators in the module docstring).

    The population is kept feasible at all times: infeasible offspring are
    rejected and replaced by feasible parents; the returned ``front`` is the
    deduplicated set of feasible individuals encountered during the run
    (entries with ``plan`` / ``objectives`` / ``feasible``, directly consumable
    by ``backend.optim.selection``).
    """
    rng = random.Random(seed)
    if ev.size_m == 0 or ev.size_s == 0:
        return {"front": [], "note": "empty MAIN/SIDE pool", "generations": 0,
                "archive_size": 0}

    def random_individual() -> np.ndarray:
        ind = np.zeros((ev.slots, 2), dtype=int)
        ind[:, 0] = rng.randrange(ev.size_m)
        ind[:, 1] = rng.randrange(ev.size_s)
        return ind

    def assess(pop_arrays: list[np.ndarray]):
        X = np.stack(pop_arrays)
        F, G, rep = ev.eval_batch(X)
        feasible = (G <= 0).all(axis=1) & ~rep
        scalars = F @ np.array([SCALAR_WEIGHTS[k] for k in OBJECTIVE_NAMES])
        return F, G, rep, feasible, scalars

    # -- initial population: one greedy-built individual + random ones -----
    pop: list[np.ndarray] = []
    greedy = _greedy_individual(ev, rng)
    if greedy is not None:
        pop.append(greedy)
    attempts = 0
    while len(pop) < pop_size and attempts < pop_size * 3:
        attempts += 1
        cand = random_individual()
        if not pop:
            # no feasible seed yet: repair random candidates until one lands
            fixed = _repair_individual(ev, cand, max_iters=repair_iters)
            if fixed is not None:
                pop.append(fixed)
        else:
            pop.append(cand)
    if not pop:
        pop = [random_individual()]

    F, G, rep, feasible, scalars = assess(pop)
    # guarantee at least one feasible member (repair the least-violating)
    if not feasible.any():
        for idx in np.argsort(scalars):
            fixed = _repair_individual(ev, pop[int(idx)], max_iters=repair_iters)
            if fixed is not None:
                pop[int(idx)] = fixed
                F, G, rep, feasible, scalars = assess(pop)
                break
    if not feasible.any():
        return {
            "front": [],
            "note": "no feasible 2-dish individual reachable (greedy + repair failed)",
            "generations": 0,
            "archive_size": 0,
        }

    archive: dict[tuple, np.ndarray] = {}

    def remember(ind: np.ndarray) -> None:
        archive.setdefault(tuple(map(tuple, np.asarray(ind, dtype=int))), ind)

    for ind, f in zip(pop, feasible):
        if f:
            remember(ind)

    def tournament() -> np.ndarray:
        feas_idx = [i for i in range(len(pop)) if feasible[i]]
        pool_idx = feas_idx if feas_idx else list(range(len(pop)))
        contenders = [rng.choice(pool_idx) for _ in range(tournament_k)]
        return pop[min(contenders, key=lambda i: float(scalars[i]))]

    generations = 0
    for _gen in range(n_gen):
        generations += 1
        # elitism: carry the two best feasible individuals untouched
        feas_idx = [i for i in range(len(pop)) if feasible[i]]
        elites = [pop[i].copy() for i in
                  sorted(feas_idx, key=lambda i: float(scalars[i]))[:2]]
        children: list[np.ndarray] = list(elites)
        while len(children) < pop_size:
            p1, p2 = tournament(), tournament()
            # uniform slot-swap crossover: per slot the whole (main, side)
            # pair swaps with probability 0.5
            mask = np.array([rng.random() < 0.5 for _ in range(ev.slots)])
            child = np.where(mask[:, None], p1, p2).astype(int)
            # slot-resample mutation: 1-3 random slots, main and/or side
            # index resampled uniformly
            for slot in rng.sample(range(ev.slots), rng.randint(1, 3)):
                if rng.random() < 0.5:
                    child[slot, 0] = rng.randrange(ev.size_m)
                if rng.random() < 0.5:
                    child[slot, 1] = rng.randrange(ev.size_s)
            children.append(child)
        _F2, _G2, _rep2, feasible2, _scalars2 = assess(children)
        # reject infeasible offspring: replace them with feasible parents
        parent_pool = [pop[i] for i in feas_idx] or [pop[0]]
        for i in range(pop_size):
            if feasible2[i]:
                remember(children[i])
            else:
                children[i] = rng.choice(parent_pool).copy()
        pop = children
        F, G, rep, feasible, scalars = assess(pop)
        for ind, f in zip(pop, feasible):
            if f:
                remember(ind)

    # final front: deduplicated feasible individuals (population + archive)
    front_individuals: list[np.ndarray] = list(archive.values())
    entries = []
    for ind in front_individuals:
        F_i, G_i, rep_i = ev.eval_single(ind)
        if (G_i <= 0).all() and not rep_i:
            entries.append({
                "plan": ev.to_plan(ind),
                "objectives": {
                    name: float(v) for name, v in zip(OBJECTIVE_NAMES, F_i)
                },
                "feasible": True,
            })
    return {
        "front": entries,
        "generations": generations,
        "archive_size": len(archive),
        "note": None,
    }


# ---------------------------------------------------------------------------
# Phase 2 driver — bounded composition ablation
# ---------------------------------------------------------------------------
def eligible_patients(patients: list[dict[str, Any]], limit: Optional[int] = None
                      ) -> list[dict[str, Any]]:
    """Eligible (non-REJECTED) patients, optionally limited to the first N."""
    out: list[dict[str, Any]] = []
    for patient in patients:
        engine_result = run_rules(patient)
        if engine_result["envelope"]["status"] == "REJECTED":
            continue
        out.append(patient)
        if limit is not None and len(out) >= limit:
            break
    return out


def evaluate_composition_ablation(
    patients: list[dict[str, Any]],
    dishes: list[Dish],
    internals: dict[tuple[str, int], dict[str, Any]],
    seed: int,
    pop_size: int = 40,
    n_gen: int = 60,
    max_patients: int = 8,
    repair_iters: int = 200,
) -> dict[str, Any]:
    """Compare the 2-dish (main + side) encoding against the 1-dish encoding.

    Uses the SAME fronts the selection phase produced (paired: identical
    solve, identical three selections).  Informational only — see
    :data:`_COMPOSITION_NOTE`.
    """
    from shared.envelope_schema import NutrientEnvelope

    subset = eligible_patients(patients, limit=max_patients)

    per_patient: list[dict[str, Any]] = []
    strategy_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        "one_dish": {name: [] for name in STRATEGY_NAMES},
        "two_dish": {name: [] for name in STRATEGY_NAMES},
    }
    pool_sizes: dict[str, Any] = {}
    notes: list[str] = []

    for patient in subset:
        envelope_dict = run_rules(patient)["envelope"]
        approved = _approve(NutrientEnvelope(**envelope_dict))
        row: dict[str, Any] = {"patient_id": approved.patient_id}

        one_entries = (internals.get((approved.patient_id, seed)) or {}).get("front") or []
        if one_entries:
            one_metrics: dict[str, dict[str, Any]] = {}
            for name, selector in _STRATEGIES.items():
                entry = selector(one_entries, approved, dishes)
                one_metrics[name] = plan_metrics(entry["plan"], approved, dishes)
                strategy_rows["one_dish"][name].append(one_metrics[name])
            row["one_dish"] = {"front_size": len(one_entries),
                               "strategies": one_metrics}
        else:
            row["one_dish"] = None
            notes.append(
                f"{approved.patient_id}: no 1-dish front (solver diagnosis); "
                "1-dish side of the comparison skipped"
            )

        ev = CompositionEvaluator(approved, dishes)
        pool_sizes.setdefault("main_pool_size", ev.size_m)
        pool_sizes.setdefault("side_pool_size", ev.size_s)
        pool_sizes["fallback_used"] = pool_sizes.get("fallback_used") or ev.fallback_used
        ga = composition_ga(ev, seed=seed, pop_size=pop_size, n_gen=n_gen,
                            repair_iters=repair_iters)
        two_entries = ga["front"]
        if two_entries:
            two_metrics: dict[str, dict[str, Any]] = {}
            for name, selector in _STRATEGIES.items():
                entry = selector(two_entries, approved, dishes)
                two_metrics[name] = plan_metrics(entry["plan"], approved, dishes)
                strategy_rows["two_dish"][name].append(two_metrics[name])
            row["two_dish"] = {
                "front_size": len(two_entries),
                "generations": ga["generations"],
                "strategies": two_metrics,
            }
        else:
            row["two_dish"] = None
            notes.append(
                f"{approved.patient_id}: "
                f"{ga.get('note') or 'no feasible 2-dish individual'}"
            )
        per_patient.append(row)

    pooled = {
        encoding: {
            name: _pool_strategy_metrics(strategy_rows[encoding][name])
            for name in STRATEGY_NAMES
        }
        for encoding in ("one_dish", "two_dish")
    }
    return {
        "note": _COMPOSITION_NOTE,
        "config": {
            "patients": len(subset),
            "seed": seed,
            "pop_size": pop_size,
            "n_gen": n_gen,
            "tournament_k": 3,
            "operators": (
                "tournament selection (k=3) on scalar_score; uniform slot-swap "
                "crossover (whole (main, side) pair swaps with p=0.5); "
                "slot-resample mutation (1-3 random slots, main and/or side "
                "index resampled uniformly); 2-scalar-elitism; infeasible "
                "offspring rejected and replaced by feasible parents"
            ),
            "main_excluded_categories": sorted(MAIN_EXCLUDED_CATEGORIES),
            "side_categories": sorted(SIDE_CATEGORIES),
            "side_tag": SIDE_TAG,
            "repetition_limit": "no dish id twice within the same day",
            "front_definition": (
                "deduplicated feasible individuals encountered by the GA"
            ),
        },
        "pools": {
            "main_pool_size": pool_sizes.get("main_pool_size"),
            "side_pool_size": pool_sizes.get("side_pool_size"),
            "fallback_used": bool(pool_sizes.get("fallback_used")),
        },
        "pooled": pooled,
        "per_patient": per_patient,
        "phase_notes": notes,
    }


# ---------------------------------------------------------------------------
# Phase 3 — exact-reference quality reporting
# ---------------------------------------------------------------------------
def evaluate_exact_reference(
    per_patient: list[dict[str, Any]],
    internals: dict[tuple[str, int], dict[str, Any]],
    dishes: list[Dish],
    approved_by_patient: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Per-patient exact-reference gaps for the scalar-selected plan.

    ``approved_by_patient`` maps patient_id -> APPROVED envelope.  Uses the
    scalar-selected plan of ``seed`` from the selection phase.
    """
    from backend.optim.exact_reference import plan_vs_exact

    rows: list[dict[str, Any]] = []
    for patient in per_patient:
        if not patient.get("attempted"):
            continue
        patient_id = patient["patient_id"]
        internal = internals.get((patient_id, seed))
        plan = (internal or {}).get("scalar_plan") or []
        envelope = approved_by_patient[patient_id]
        if not plan:
            rows.append({
                "patient_id": patient_id,
                "has_plan": False,
                "mean_gaps": None,
                "at_per_day_optimum": None,
                "seven_day_lower_bounds": None,
            })
            continue
        ref = plan_vs_exact(envelope, dishes, plan)
        mean_gaps: dict[str, Any] = {}
        at_opt: dict[str, bool] = {}
        bounds: dict[str, Any] = {}
        for name, entry in ref["objectives"].items():
            mean_gaps[name] = entry["mean_gap"]
            bounds[name] = entry["seven_day_lower_bound"]
            gaps = entry.get("gaps")
            at_opt[name] = bool(
                gaps is not None and all(g <= _OPTIMUM_GAP_TOL for g in gaps)
            )
        rows.append({
            "patient_id": patient_id,
            "has_plan": True,
            "mean_gaps": mean_gaps,
            "at_per_day_optimum": at_opt,
            "seven_day_lower_bounds": bounds,
            "exact_pool_size": ref["exact"]["pool_size"],
            "feasible_combo_count": ref["exact"]["feasible_combo_count"],
        })

    additive = ("nutrient_target_deviation", "preference_sum", "cost")
    aggregate = {
        name: {
            "mean_gap": _mean([
                r["mean_gaps"][name] for r in rows
                if r.get("has_plan") and r["mean_gaps"]
                and r["mean_gaps"][name] is not None
            ]),
            "patients_at_per_day_optimum": sum(
                1 for r in rows
                if r.get("has_plan") and r["at_per_day_optimum"]
                and r["at_per_day_optimum"].get(name)
            ),
            "plans_with_reference": sum(1 for r in rows if r.get("has_plan")),
        }
        for name in additive
    }
    status_counts = Counter(
        internals[(p["patient_id"], seed)]["infeasibility_status"]
        for p in per_patient
        if p.get("attempted") and (p["patient_id"], seed) in internals
    )
    return {
        "seed": seed,
        "per_patient": rows,
        "aggregate": aggregate,
        "infeasibility_status_counts": dict(status_counts),
        "excluded_objectives": ["variety"],
        "disclosure": _EXACT_DISCLOSURE,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def evaluate_q6(
    patients: list[dict[str, Any]] | None = None,
    dishes: list[Dish] | None = None,
    seeds: tuple[int, ...] = SEEDS,
    pop_size: int = 40,
    n_gen: int = 80,
    composition_patients: int = 8,
    composition_pop: int = 40,
    composition_gen: int = 60,
    composition_seed: Optional[int] = None,
) -> dict[str, Any]:
    """Q6: selection ablation -> composition ablation -> exact reference."""
    from shared.envelope_schema import NutrientEnvelope

    patients = patients if patients is not None else load_patients()
    if dishes is None:
        from backend.optim.real_data import load_dishes

        dishes = load_dishes()
    composition_seed = seeds[0] if composition_seed is None else composition_seed

    selection, internals = evaluate_selection_ablation(
        patients, dishes, seeds=seeds, pop_size=pop_size, n_gen=n_gen
    )
    verdict, verdict_note = derive_selection_verdict(selection["pooled"])

    composition = evaluate_composition_ablation(
        patients, dishes, internals, seed=composition_seed,
        pop_size=composition_pop, n_gen=composition_gen,
        max_patients=composition_patients,
    )

    approved_by_patient: dict[str, Any] = {}
    for patient in patients:
        engine_result = run_rules(patient)
        envelope_dict = engine_result["envelope"]
        if envelope_dict["status"] == "REJECTED":
            continue
        approved = _approve(NutrientEnvelope(**envelope_dict))
        approved_by_patient[approved.patient_id] = approved

    exact = evaluate_exact_reference(
        selection["per_patient"], internals, dishes,
        approved_by_patient, seed=seeds[0],
    )

    return {
        "question": "Q6 Objective/selection & meal-composition ablation",
        "definition": (
            "P1 review comparison: current raw-unit scalar selection vs "
            "nutrient-normalised selection vs adequacy-first/lexicographic "
            "selection on the SAME NSGA-II fronts, scored against the "
            "ORIGINAL approved aims (paired patient/seed design), followed "
            "by a bounded meal-composition ablation (1 dish/slot vs main+side "
            "2-dish encoding, production encoding unchanged) and "
            "exact-reference quality reporting for the scalar-selected plans."
        ),
        "selection_ablation": selection,
        "composition_ablation": composition,
        "exact_reference": exact,
        "verdict": verdict,
        "verdict_note": verdict_note,
    }
