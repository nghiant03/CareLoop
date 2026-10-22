"""Single dish search with repair and exact failure diagnosis."""

from __future__ import annotations

import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

from backend.optim import baselines
from backend.optim.problem import (
    OBJECTIVE_NAMES,
    allowed_dishes,
    evaluate,
    scalar_score,
    violation_magnitude,
)

from .exact_reference import one_day_exact
from .real_data import (
    FastEvaluator,
    feasibility_precheck,
    greedy_feasible_plan,
    repair_plan,
)

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

# Optional comparison dependencies must not break production NSGA II.
REF_DIRS_4OBJ = None
try:  # pragma: no cover - depends on environment
    from pymoo.algorithms.moo.age import AGEMOEA
    from pymoo.algorithms.moo.moead import MOEAD
    from pymoo.algorithms.moo.nsga3 import NSGA3
    from pymoo.algorithms.moo.sms import SMSEMOA
    from pymoo.decomposition.pbi import PBI
    from pymoo.util.ref_dirs import get_reference_directions

    if HAS_PYMOO:
        REF_DIRS_4OBJ = get_reference_directions("das-dennis", 4, n_partitions=4)
    HAS_PYMOO_EXTRAS = HAS_PYMOO
    PYMOO_EXTRAS_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    HAS_PYMOO_EXTRAS = False
    PYMOO_EXTRAS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

PYMOO_METHODS = ("nsga2", "nsga3", "moead", "age", "sms")


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


def _build_pymoo_algorithm(method: str, pop_size: int):
    """MOEA/D population follows the reference direction count rather than pop_size."""
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
    """MOEA/D drops inequalities during search. The guarantee still validates the reported plan."""
    problem = _build_pymoo_problem(ev, with_constraints=(method != "moead"))
    algorithm = _build_pymoo_algorithm(method, pop_size)
    res = minimize(problem, algorithm, termination or ("n_gen", n_gen), seed=seed, verbose=False)
    evaluations = int(res.algorithm.evaluator.n_eval)
    if res.X is None:
        return _SearchFront([], evaluations)
    X = np.atleast_2d(np.asarray(res.X, dtype=int))
    return _SearchFront([X[i] for i in range(len(X))], evaluations)


def ga_search(envelope, dishes, seed: int = 42, pop_size: int = 40, n_gen: int = 80) -> dict:
    """Scalar ranking does not spread a Pareto front."""
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
        weights = [float(pop_size - r) for r in range(len(scored))]
        total = sum(weights)

        def select(total: float = total, weights: list[float] = weights):
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


def greedy_search(envelope, dishes, seed: int = 0) -> dict:
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


def _entry(ev: FastEvaluator, idx: np.ndarray) -> dict:
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
    return {
        "feasible_day": exact["feasible_day"],
        "feasible_combo_count": exact["feasible_combo_count"],
        "pool_size": exact["pool_size"],
    }


def _diagnose_with_exact(
    envelope, dishes, reason: str, runtime_ms: float, allowed_count: int
) -> dict:
    """Exact diagnosis covers single dish encoding rather than main and side composition."""
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
    """Custom selectors must return an unchanged supplied feasible entry. Their result is not revalidated."""
    feasible = [e for e in entries if e["feasible"]]
    if feasible:
        if selection is not None:
            best = selection(feasible, ev.envelope, ev.dishes)
        else:
            best = min(feasible, key=lambda e: scalar_score(e["objectives"]))
        return best, engine, feasible

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
    """Guarantees apply only to pymoo family methods. Baselines stay raw and custom selectors must preserve entries."""
    t0 = time.perf_counter()
    allowed = allowed_dishes(envelope, dishes)

    ok, reason = feasibility_precheck(envelope, dishes)
    if not ok:
        assert reason is not None
        # Confirm failed prechecks exactly before reporting infeasibility.
        exact = one_day_exact(envelope, dishes)
        if not exact["feasible_day"]:
            diag = _diagnosis(
                envelope, dishes, reason, (time.perf_counter() - t0) * 1000.0, len(allowed)
            )
            diag["infeasibility_status"] = "proven_infeasible"
            diag["exact_reference"] = _exact_reference_summary(exact)
            return diag

    ev = FastEvaluator(envelope, dishes)

    if method in PYMOO_METHODS:
        if method != "nsga2" and not HAS_PYMOO_EXTRAS:
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
    "PYMOO_EXTRAS_IMPORT_ERROR",
    "PYMOO_IMPORT_ERROR",
    "PYMOO_METHODS",
    "ga_search",
    "greedy_search",
    "random_search",
    "solve",
]
