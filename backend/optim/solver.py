"""Single-dish search with canonical validation, repair, and exact failure diagnosis.

Production NSGA-II uses pymoo when available, otherwise a hand-rolled GA.
Guaranteed pymoo-method runs return a hard-feasible plan or an empty diagnosed
result. Bounded repair/construction can miss feasible plans; exact one-day
enumeration distinguishes search exhaustion from proven single-dish infeasibility.

Raw pymoo mode and benchmark baselines may return violating plans. The exact
reference does not prove infeasibility for main/side composition. See ``solve``
for method/selection contracts and ``exact_reference`` for proof assumptions.
"""

from __future__ import annotations

import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

from backend.optim import baselines  # noqa: E402
from backend.optim.problem import (  # noqa: E402
    OBJECTIVE_NAMES,
    allowed_dishes,
    evaluate,
    scalar_score,
    violation_magnitude,
)

from .exact_reference import one_day_exact  # noqa: E402
from .real_data import (  # noqa: E402
    FastEvaluator,
    feasibility_precheck,
    greedy_feasible_plan,
    repair_plan,
)

# ---------------------------------------------------------------------------
# Lazy pymoo import (same pattern as spike_pymoo.py)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    from pymoo.optimize import minimize

    HAS_PYMOO = True
    PYMOO_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    HAS_PYMOO = False
    PYMOO_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# Extra pymoo algorithms for the benchmark comparison.  Kept in a *separate*
# guarded block so a broken optional dependency (e.g. AGEMOEA needs numba)
# can never break the production NSGA-II path above.
try:  # pragma: no cover - depends on environment
    from pymoo.algorithms.moo.age import AGEMOEA
    from pymoo.algorithms.moo.moead import MOEAD
    from pymoo.algorithms.moo.nsga3 import NSGA3
    from pymoo.algorithms.moo.sms import SMSEMOA
    from pymoo.decomposition.pbi import PBI
    from pymoo.util.ref_dirs import get_reference_directions

    HAS_PYMOO_EXTRAS = HAS_PYMOO
    PYMOO_EXTRAS_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    HAS_PYMOO_EXTRAS = False
    PYMOO_EXTRAS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# Methods that run through the pymoo front search (NSGA-II + the benchmark
# comparison set).  All of them share the hard feasibility guarantee in
# ``solve()`` unless ``guarantee=False`` is passed explicitly (raw mode).
PYMOO_METHODS = ("nsga2", "nsga3", "moead", "age", "sms")


# ---------------------------------------------------------------------------
# pymoo problem wrapper over FastEvaluator
# ---------------------------------------------------------------------------
def _build_pymoo_problem(ev: FastEvaluator, with_constraints: bool = True):
    class _FastMealPlanProblem(Problem):  # type: ignore[misc, valid-type]
        def __init__(self):
            super().__init__(
                n_var=ev.slots,
                n_obj=len(OBJECTIVE_NAMES),
                n_ieq_constr=ev.n_constraints if with_constraints else 0,
                xl=0,
                xu=ev.size - 1,
                vtype=int,
            )
            self._ev = ev
            self._with_constraints = with_constraints

        def _evaluate(self, X, out, *args, **kwargs):
            F, G = self._ev.eval_batch(X)
            out["F"] = F
            if self._with_constraints:
                out["G"] = G

    return _FastMealPlanProblem()


# Das-Dennis reference directions for 4 objectives, divergence p=4 ->
# 35 uniformly spread directions.  Used by NSGA-III (survival) and MOEA/D
# (weight vectors); 35 is close to the benchmark's pop=40 budget so all
# methods compare at a similar evaluation count.
REF_DIRS_4OBJ = None
if HAS_PYMOO_EXTRAS:  # pragma: no branch
    REF_DIRS_4OBJ = get_reference_directions("das-dennis", 4, n_partitions=4)


def _build_pymoo_algorithm(method: str, pop_size: int):
    """Instantiate the pymoo algorithm for ``method``.

    All genetic operators are shared with the production NSGA-II config
    (IntegerRandomSampling + SBX + PM) so the comparison isolates the
    *selection/survival* mechanism, not the variation operators.

    Parameter choices for the 4-objective problem:

    * ``nsga3`` — das-dennis p=4 reference directions (35 dirs, pop_size 40
      covers them); NSGA-III survival niches onto the directions.
    * ``moead`` — same 35 weight vectors, T=15 neighbours, PBI decomposition
      (theta default 5), neighbourhood mating prob 0.9.  Its population size
      is tied to the weight-vector count (35), noted in the benchmark.
    * ``age`` — AGE-MOEA survival (geometry-adaptive crowding); numba-backed.
    * ``sms`` — SMSEMOA, exact hypervolume contribution survival in 4-D;
      pop_size kept at 40 to bound the HV-contribution cost.
    """
    sampling = IntegerRandomSampling()
    crossover = SBX(prob=0.9, eta=15)
    mutation = PM(eta=20)
    if method == "nsga2":
        return NSGA2(
            pop_size=pop_size,
            sampling=sampling,
            crossover=crossover,
            mutation=mutation,
            eliminate_duplicates=True,
        )
    if method == "nsga3":
        return NSGA3(
            ref_dirs=REF_DIRS_4OBJ,
            pop_size=pop_size,
            sampling=sampling,
            crossover=crossover,
            mutation=mutation,
            eliminate_duplicates=True,
        )
    if method == "moead":
        # MOEA/D: population size is len(ref_dirs) = 35 (not pop_size).
        return MOEAD(
            ref_dirs=REF_DIRS_4OBJ,
            n_neighbors=15,
            decomposition=PBI(theta=5.0),
            prob_neighbor_mating=0.9,
            sampling=sampling,
            crossover=crossover,
            mutation=mutation,
        )
    if method == "age":
        return AGEMOEA(
            pop_size=pop_size,
            sampling=sampling,
            crossover=crossover,
            mutation=mutation,
            eliminate_duplicates=True,
        )
    if method == "sms":
        return SMSEMOA(
            pop_size=pop_size,
            sampling=sampling,
            crossover=crossover,
            mutation=mutation,
            eliminate_duplicates=True,
        )
    raise ValueError(f"unknown pymoo method {method!r}")


class _SearchFront(list):
    def __init__(self, entries, evaluations):
        super().__init__(entries)
        self.evaluations = evaluations


def _pymoo_front(
    ev: FastEvaluator, seed: int, pop_size: int, n_gen: int, method: str = "nsga2",
    termination=None,
) -> list[np.ndarray]:
    """Run a pymoo algorithm and return the non-dominated plans as index arrays.

    MOEA/D's pymoo implementation cannot represent inequality constraints, so
    it runs on the unconstrained view of the same problem (objectives
    unchanged, hard-constraint vector dropped) — infeasible members can then
    dominate feasible ones inside its decomposition; the guarantee wrapper in
    ``solve()`` still fences the *reported* plan.  This is noted in the
    benchmark report.
    """
    problem = _build_pymoo_problem(ev, with_constraints=(method != "moead"))
    algorithm = _build_pymoo_algorithm(method, pop_size)
    res = minimize(problem, algorithm, termination or ("n_gen", n_gen), seed=seed, verbose=False)
    evaluations = int(res.algorithm.evaluator.n_eval)
    if res.X is None:
        return _SearchFront([], evaluations)
    X = np.atleast_2d(np.asarray(res.X, dtype=int))
    return _SearchFront([X[i] for i in range(len(X))], evaluations)


# ---------------------------------------------------------------------------
# Hand-rolled GA baseline (single-objective, roulette + crossover + mutation)
# ---------------------------------------------------------------------------
def ga_search(envelope, dishes, seed: int = 42, pop_size: int = 40, n_gen: int = 80) -> dict:
    """Simple generational GA: roulette selection, uniform crossover, flip mutation.

    Deliberately *not* NSGA-II: it scalarises objectives and treats constraint
    violations as a lexicographic penalty, so it cannot spread a Pareto front.
    """
    t0 = time.perf_counter()
    ev = FastEvaluator(envelope, dishes)
    if ev.size == 0 or ev.slots == 0:
        return baselines._make_result("ga", [], envelope, dishes, 0, 0.0)

    rng = random.Random(seed)
    pop = [
        np.array([rng.randrange(ev.size) for _ in range(ev.slots)], dtype=int)
        for _ in range(pop_size)
    ]
    evaluations = 0

    def assess(idx) -> tuple:
        f, g = ev.eval_indices(idx)
        nviol = int((g > 0).sum())
        mag = float(np.maximum(g, 0.0).sum())
        return f, nviol, mag, ev.scalar(f)

    scored = [(ind, *assess(ind)) for ind in pop]
    evaluations += len(pop)

    for _gen in range(n_gen):
        scored.sort(key=lambda t: (t[2], t[3], t[4]))
        # Roulette weights favour low rank (fewer/smaller violations first).
        weights = [float(pop_size - r) for r in range(len(scored))]
        total = sum(weights)

        def select():
            pick = rng.random() * total
            acc = 0.0
            for i, w in enumerate(weights):
                acc += w
                if acc >= pick:
                    return i
            return len(weights) - 1

        def crossover(p1, p2):
            mask = [rng.random() < 0.5 for _ in range(ev.slots)]
            child = np.array(
                [p1[j] if mask[j] else p2[j] for j in range(ev.slots)], dtype=int
            )
            for j in range(ev.slots):
                if rng.random() < 1.0 / ev.slots:
                    child[j] = rng.randrange(ev.size)
            return child

        # Elitism: carry the two best individuals.
        next_pop = [scored[0][0].copy(), scored[1][0].copy()]
        while len(next_pop) < pop_size:
            p1 = scored[select()][0]
            p2 = scored[select()][0]
            child = crossover(p1, p2)
            next_pop.append(child)

        scored = [(ind, *assess(ind)) for ind in next_pop]
        evaluations += len(next_pop)

    scored.sort(key=lambda t: (t[2], t[3], t[4]))
    best_idx = scored[0][0]
    runtime = (time.perf_counter() - t0) * 1000.0
    return baselines._make_result(
        "ga", ev.idx_to_plan(best_idx), envelope, dishes, evaluations, runtime
    )


# ---------------------------------------------------------------------------
# Greedy / random wrappers (raw baselines — no guarantee applied)
# ---------------------------------------------------------------------------
def greedy_search(envelope, dishes, seed: int = 0) -> dict:
    """Feasibility-aware greedy construction with cross-day variety pressure."""
    t0 = time.perf_counter()
    ev = FastEvaluator(envelope, dishes)
    if ev.size == 0:
        return baselines._make_result("greedy", [], envelope, dishes, 0, 0.0)
    idx = greedy_feasible_plan(ev, seed=seed)
    if idx is None:
        return baselines._make_result("greedy", [], envelope, dishes, 0, 0.0)
    runtime = (time.perf_counter() - t0) * 1000.0
    return baselines._make_result(
        "greedy", ev.idx_to_plan(idx), envelope, dishes, ev.size * ev.slots, runtime
    )


def random_search(envelope, dishes, seed: int = 0, n_iter: int = 300) -> dict:
    return baselines.random_search(envelope, dishes, n_iter=n_iter, seed=seed)


# ---------------------------------------------------------------------------
# solve(): production pipeline with the hard feasibility guarantee
# ---------------------------------------------------------------------------
def _entry(ev: FastEvaluator, idx: np.ndarray) -> dict:
    """Canonical evaluation of a pool plan (source of truth for reporting)."""
    plan = ev.idx_to_plan(idx)
    objectives, violations = evaluate(plan, ev.envelope, ev.dishes)
    return {
        "plan": plan,
        "objectives": objectives,
        "violations": violations,
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
    }


def _diagnosis(
    envelope, dishes, reason: str, runtime_ms: float, allowed_count: int
) -> dict:
    """Explicit infeasibility result — never a silently broken plan."""
    return {
        "method": "diagnosis",
        "engine": "infeasible",
        "plan": [],
        "objectives": {k: 0.0 for k in OBJECTIVE_NAMES},
        "violations": [
            {
                "type": "infeasible_pool",
                "amount": float("inf"),
                "detail": reason,
            }
        ],
        "violation_count": 1,
        "feasible": False,
        "evaluations": 0,
        "runtime_ms": round(runtime_ms, 3),
        "front": [],
        "front_size": 0,
        "infeasibility_reason": reason,
        "envelope_id": envelope.envelope_id,
        "patient_id": envelope.patient_id,
        "allowed_dish_count": allowed_count,
    }


def _exact_reference_summary(exact: dict) -> dict:
    """Compact ``one_day_exact`` summary embedded in diagnosed results."""
    return {
        "feasible_day": exact["feasible_day"],
        "feasible_combo_count": exact["feasible_combo_count"],
        "pool_size": exact["pool_size"],
    }


def _diagnose_with_exact(
    envelope, dishes, reason: str, runtime_ms: float, allowed_count: int
) -> dict:
    """Diagnosis enriched with the exact one-day enumeration verdict.

    ``infeasibility_status`` semantics:

    * ``"proven_infeasible"`` — exhaustive one-day enumeration
      (:func:`exact_reference.one_day_exact`) found NO feasible dish multiset.
      Each slot holds exactly one dish, and a feasible horizon requires each
      day to pass the daily hard checks. No feasible day therefore proves that
      no 7-day plan exists in this encoding.
    * ``"search_exhausted"`` — a feasible day exists, but search, repair, and
      greedy construction failed to deliver a canonically feasible plan.
      This is not an infeasibility proof. A feasible day is necessary, not
      strictly sufficient: repeating a day within the daily ``problem.EPS``
      tolerance can exceed the horizon tolerance. The canonical evaluator
      validates the delivered plan.

    Greedy construction and single-slot repair are incomplete; successful exact
    enumeration does not imply that either heuristic will find a feasible day.
    """
    exact = one_day_exact(envelope, dishes)
    diag = _diagnosis(envelope, dishes, reason, runtime_ms, allowed_count)
    diag["infeasibility_status"] = (
        "proven_infeasible" if not exact["feasible_day"] else "search_exhausted"
    )
    diag["exact_reference"] = _exact_reference_summary(exact)
    return diag


def _guarantee(
    ev: FastEvaluator,
    entries: list[dict],
    seed: int,
    engine: str,
    selection=None,
) -> tuple[dict | None, str, list[dict]]:
    """Find a feasible entry via bounded repair/construction, or return None.

    ``selection``: optional ``(entries, envelope, dishes) -> entry`` callable
    used to pick the headline plan from the feasible entries instead of the
    default ``min(..., key=scalar_score)`` (see ``backend.optim.selection``).
    ``None`` uses scalar score. A custom selector must return one of the supplied
    feasible entries without mutating it; the callback result is not revalidated.

    Returns ``(best_entry, engine_label, feasible_entries)`` or ``(None, ...)``
    when no feasible plan could be reached.
    """
    feasible = [e for e in entries if e["feasible"]]
    if feasible:
        if selection is not None:
            best = selection(feasible, ev.envelope, ev.dishes)
        else:
            best = min(feasible, key=lambda e: scalar_score(e["objectives"]))
        return best, engine, feasible

    # 1) repair the least-violating candidate
    if entries:
        repair_candidate = min(
            entries,
            key=lambda e: (
                e["violation_count"],
                violation_magnitude(e["violations"]),
                scalar_score(e["objectives"]),
            ),
        )
        try:
            idx = ev.plan_to_idx(repair_candidate["plan"])
        except KeyError:
            idx = None
        if idx is not None:
            fixed = repair_plan(ev, idx, seed=seed)
            if fixed is not None:
                entry = _entry(ev, fixed)
                if entry["feasible"]:
                    feasible.append(entry)
                    return entry, f"{engine}+repair", feasible

    # 2) greedy-constructed feasible plan
    gidx = greedy_feasible_plan(ev, seed=seed)
    if gidx is not None:
        entry = _entry(ev, gidx)
        if entry["feasible"]:
            feasible.append(entry)
            return entry, "greedy-fallback", feasible

    return None, engine, feasible


def solve(
    envelope,
    dishes,
    seed: int = 42,
    pop_size: int = 40,
    n_gen: int = 80,
    method: str = "nsga2",
    guarantee: bool = True,
    selection=None,
    termination=None,
) -> dict:
    """Search one dish per slot and return plan metrics, front entries, or a diagnosis.

    ``method`` selects production ``"nsga2"``, pymoo benchmark comparisons
    ``"nsga3"`` / ``"moead"`` / ``"age"`` / ``"sms"``, or raw benchmark
    baselines ``"ga"`` / ``"greedy"`` / ``"random"``. Unavailable optional
    comparison algorithms raise ``RuntimeError`` with the import error.
    ``"nsga2"`` retains its GA fallback.

    ``guarantee`` applies only to pymoo-family methods, including the NSGA-II
    fallback. True enables repair/construction and explicit empty-plan failure.
    False selects the least-violating/best-scalar raw entry. Baseline methods
    remain raw regardless of this option. Failed prechecks are confirmed by exact
    enumeration before either path; passing a precheck does not prove feasibility.

    ``selection``: optional ``(entries, envelope, dishes) -> entry`` callable
    used instead of the default ``min(..., key=scalar_score)`` when picking the
    headline plan from the feasible front in ``_guarantee`` (see
    ``backend.optim.selection``).  ``None`` (default) keeps the current
    scalar-score ordering. The callback must return an unchanged supplied entry;
    its result is not revalidated. ``termination`` is forwarded to pymoo search
    only, not fallback GA or baseline methods.
    """
    t0 = time.perf_counter()
    allowed = allowed_dishes(envelope, dishes)

    ok, reason = feasibility_precheck(envelope, dishes)
    if not ok:
        # Confirm a failed precheck with exhaustive one-day enumeration.
        # No feasible day proves infeasibility for this single-dish encoding.
        # A feasible day lets search continue, but does not prove horizon
        # feasibility: repeated daily EPS excess can exceed horizon EPS.
        exact = one_day_exact(envelope, dishes)
        if not exact["feasible_day"]:
            diag = _diagnosis(
                envelope, dishes, reason, (time.perf_counter() - t0) * 1000.0, len(allowed)
            )
            diag["infeasibility_status"] = "proven_infeasible"
            diag["exact_reference"] = _exact_reference_summary(exact)
            return diag
        # exact enumeration found a feasible day: fall through and keep solving.

    ev = FastEvaluator(envelope, dishes)

    if method in PYMOO_METHODS:
        if method != "nsga2" and not HAS_PYMOO_EXTRAS:
            # Actionable diagnostic when the optional comparison algorithms
            # failed to import (e.g. AGEMOEA needs numba): a NameError from
            # _build_pymoo_algorithm would say nothing actionable. NSGA-II is
            # exempt so the production fallback below stays reachable.
            reason = PYMOO_EXTRAS_IMPORT_ERROR or PYMOO_IMPORT_ERROR
            raise RuntimeError(
                f"method {method!r} requires the pymoo comparison algorithms "
                f"(import failed: {reason})"
            )
        if HAS_PYMOO:
            engine = "pymoo"
            options = {"termination": termination} if termination is not None else {}
            idxs = _pymoo_front(ev, seed, pop_size, n_gen, method=method, **options)
            evaluations = getattr(idxs, "evaluations", 0)
        elif method == "nsga2":
            # Production fallback: hand-rolled GA when pymoo is unavailable.
            engine = "fallback-ga"
            raw = ga_search(envelope, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen)
            evaluations = raw["evaluations"]
            idxs = [ev.plan_to_idx(raw["plan"])] if raw["plan"] else []
        else:
            raise RuntimeError(
                f"method {method!r} requires pymoo (import failed: {PYMOO_IMPORT_ERROR})"
            )
        entries = [_entry(ev, i) for i in idxs]

        if not guarantee:
            # Raw mode: report the raw front untouched.  Headline plan is the
            # least-violating / best-scalar member (same ranking the raw
            # baselines use), so honest violation rates are measurable.
            engine = "pymoo-raw"
            if entries:
                best = min(
                    entries,
                    key=lambda e: (
                        e["violation_count"],
                        violation_magnitude(e["violations"]),
                        scalar_score(e["objectives"]),
                    ),
                )
            else:
                best = None
            runtime = (time.perf_counter() - t0) * 1000.0
            result = baselines._make_result(
                method,
                best["plan"] if best else [],
                envelope,
                dishes,
                evaluations,
                runtime,
                front=entries,
                front_size=len(entries),
            )
            result["engine"] = engine
            result["guaranteed"] = False
            return result

        best, engine, feasible = _guarantee(ev, entries, seed, engine, selection)
        if best is None:
            return _diagnose_with_exact(
                envelope, dishes, "no feasible plan reachable from the allowed pool",
                (time.perf_counter() - t0) * 1000.0, len(allowed),
            )
        runtime = (time.perf_counter() - t0) * 1000.0
        result = baselines._make_result(
            method,
            best["plan"],
            envelope,
            dishes,
            evaluations,
            runtime,
            front=feasible,
            front_size=len(feasible),
        )
        result["engine"] = engine
        result["guaranteed"] = True
        return result

    if method == "ga":
        result = ga_search(envelope, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen)
        result["engine"] = "ga"
        return result

    if method == "greedy":
        result = greedy_search(envelope, dishes, seed=seed)
        result["engine"] = "greedy"
        return result

    if method == "random":
        result = random_search(envelope, dishes, seed=seed)
        result["engine"] = "random"
        return result

    raise ValueError(f"unknown method {method!r}")


__all__ = [
    "HAS_PYMOO",
    "HAS_PYMOO_EXTRAS",
    "PYMOO_METHODS",
    "PYMOO_IMPORT_ERROR",
    "PYMOO_EXTRAS_IMPORT_ERROR",
    "ga_search",
    "greedy_search",
    "random_search",
    "solve",
]
