"""Production solve pipeline: NSGA-II + hard feasibility guarantee.

``solve()`` is the single entry point used by ``api.run``.  Contract:

* prefers pymoo NSGA-II (engine ``"pymoo"``); falls back to a hand-rolled GA
  (``"fallback-ga"``) when pymoo/numpy are unavailable;
* **never returns an infeasible plan**: if the search front contains no
  feasible solution, the least-violating candidate is repaired (hill-climbing
  + greedy rebuild, :func:`real_data.repair_plan`); if that fails, a
  greedy-constructed feasible plan is used; if even that is impossible the
  result is an explicit infeasibility diagnosis (``feasible=False``,
  ``infeasibility_reason`` set, empty plan) — never a silently broken plan;
* returned plans always satisfy the envelope's hard constraints (MAX ceilings
  + exclusions per PLAN.md module 4; MIN floors / TARGETs are soft) with
  ``violation_count == 0`` (verified with the canonical ``problem.evaluate``).

Benchmark baselines (``ga_search``, ``greedy_search``, ``random_search``) are
raw and may return infeasible plans — that is intentional so the harness can
measure hard-constraint violation rates per method.  The pymoo comparison
methods (``nsga3``, ``moead``, ``age``, ``sms``) run through the SAME
guarantee path as NSGA-II by default (``solve(..., method=...)``), and can be
run raw with ``guarantee=False`` for honest violation-rate measurement.
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


def _pymoo_front(
    ev: FastEvaluator, seed: int, pop_size: int, n_gen: int, method: str = "nsga2"
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
    res = minimize(problem, algorithm, ("n_gen", n_gen), seed=seed, verbose=False)
    if res.X is None:
        return []
    X = np.atleast_2d(np.asarray(res.X, dtype=int))
    return [X[i] for i in range(len(X))]


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


def _guarantee(
    ev: FastEvaluator, entries: list[dict], seed: int, engine: str
) -> tuple[dict | None, str, list[dict]]:
    """Ensure a feasible plan exists; repair / greedy-rebuild when it does not.

    Returns ``(best_entry, engine_label, feasible_entries)`` or ``(None, ...)``
    when the pool provably cannot satisfy the envelope.
    """
    feasible = [e for e in entries if e["feasible"]]
    if feasible:
        best = min(feasible, key=lambda e: scalar_score(e["objectives"]))
        return best, engine, feasible

    # 1) repair the least-violating candidate
    if entries:
        worst = min(
            entries,
            key=lambda e: (
                e["violation_count"],
                violation_magnitude(e["violations"]),
                scalar_score(e["objectives"]),
            ),
        )
        try:
            idx = ev.plan_to_idx(worst["plan"])
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
) -> dict:
    """Solve for ``envelope`` over ``dishes`` with the feasibility guarantee.

    ``method``: ``"nsga2"`` (production), the benchmark comparison set
    ``"nsga3"`` / ``"moead"`` / ``"age"`` / ``"sms"`` (all pymoo, all through
    the same guarantee path), or raw baselines ``"ga"``, ``"greedy"``,
    ``"random"`` used by the benchmark harness.

    ``guarantee``: when True (the default, and the production behaviour) the
    result carries the hard feasibility guarantee (repair / greedy fallback).
    When False the raw search front is returned untouched so the benchmark can
    measure honest hard-constraint violation rates — the headline plan is the
    least-violating/best-scalar member of the raw front.  This never weakens
    the production default; ``api.run`` never passes ``guarantee=False``.
    """
    t0 = time.perf_counter()
    allowed = allowed_dishes(envelope, dishes)

    ok, reason = feasibility_precheck(envelope, dishes)
    if not ok:
        return _diagnosis(envelope, dishes, reason, (time.perf_counter() - t0) * 1000.0, len(allowed))

    ev = FastEvaluator(envelope, dishes)

    if method in PYMOO_METHODS:
        if HAS_PYMOO:
            engine = "pymoo"
            eff_pop = pop_size
            if method == "moead" and REF_DIRS_4OBJ is not None:
                eff_pop = len(REF_DIRS_4OBJ)
            idxs = _pymoo_front(ev, seed, pop_size, n_gen, method=method)
            evaluations = len(idxs) + eff_pop * n_gen
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

        best, engine, feasible = _guarantee(ev, entries, seed, engine)
        if best is None:
            return _diagnosis(
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