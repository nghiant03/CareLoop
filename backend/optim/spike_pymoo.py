"""Toy meal-search demo with a pure-Python fallback when pymoo is unavailable.

Run with ``python -m backend.optim.spike_pymoo``. Print plan metrics and write
front objectives to ``backend/optim/spike_pymoo.csv``.
"""

from __future__ import annotations

import csv
import os
import sys
import time

# Allow direct execution: `python backend/optim/spike_pymoo.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.optim import baselines
from backend.optim.problem import (
    DAYS,
    MEALS_PER_DAY,
    OBJECTIVE_NAMES,
    allowed_dishes,
    daily_totals,
    dish_lookup,
    evaluate,
)
from backend.optim.toy_data import TOY_DISHES
from shared.envelope_schema import (
    CitationSource,
    ConstraintKind,
    EnvelopeStatus,
    ExclusionFlag,
    ExclusionKind,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)

try:  # pragma: no cover - depends on environment
    import numpy as np
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

from backend.storage_paths import artifact_dir

CSV_PATH = str(artifact_dir("optim") / "spike_pymoo.csv")


def build_sample_envelope() -> NutrientEnvelope:
    """Toy APPROVED envelope: energy TARGET + sodium/protein MAX + protein MIN."""
    return NutrientEnvelope(
        envelope_id="env-toy-001",
        patient_id="p-toy",
        status=EnvelopeStatus.APPROVED,
        version=1,
        patient_snapshot=PatientSummary(
            patient_id="p-toy",
            age=64,
            sex="M",
            weight_kg=70.0,
            diagnoses=["CKD_stage_3", "HTN", "T2D"],
        ),
        targets=[
            NutrientConstraint(
                nutrient=NutrientKind.ENERGY_KCAL,
                kind=ConstraintKind.TARGET,
                value=1900.0,
                unit="kcal",
            ),
            NutrientConstraint(
                nutrient=NutrientKind.SODIUM_MG,
                kind=ConstraintKind.MAX,
                value=2000.0,
                unit="mg",
            ),
            NutrientConstraint(
                nutrient=NutrientKind.PROTEIN_G,
                kind=ConstraintKind.MIN,
                value=60.0,
                unit="g",
            ),
            NutrientConstraint(
                nutrient=NutrientKind.PROTEIN_G,
                kind=ConstraintKind.MAX,
                value=80.0,
                unit="g",
            ),
        ],
        exclusions=[
            ExclusionFlag(
                kind=ExclusionKind.INGREDIENT,
                value="lard",
                reason="Saturated-fat / cardiovascular risk",
                citation=CitationSource(
                    guideline="KDIGO 2024", section="3.2", rule_id="R-EX-LARD"
                ),
            ),
            ExclusionFlag(
                kind=ExclusionKind.DISH_CATEGORY,
                value="deep_fried",
                reason="Fried foods worsen cardiovascular risk",
                citation=CitationSource(
                    guideline="AHA-ACC 2025", section="4.1", rule_id="R-EX-DF"
                ),
            ),
        ],
        priority_basis="CKD > HTN > T2D",
    )


def _build_pymoo_problem(envelope, dishes, slots: int):
    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    if not pool:
        raise RuntimeError("no dishes survive exclusions; problem is empty")

    from backend.optim.problem import constraint_names, constraint_vector

    n_constr = len(constraint_names(envelope, slots // MEALS_PER_DAY))
    n_pool = len(pool)

    def decode(x) -> list[list[str]]:
        return [[pool[int(i)]] for i in x]

    class _MealPlanProblem(Problem):  # type: ignore[misc, valid-type]
        def __init__(self):
            super().__init__(
                n_var=slots,
                n_obj=len(OBJECTIVE_NAMES),
                n_ieq_constr=n_constr,
                xl=0,
                xu=n_pool - 1,
                vtype=int,
            )

        def _evaluate(self, X, out, *args, **kwargs):
            f = np.zeros((len(X), len(OBJECTIVE_NAMES)))
            g = np.zeros((len(X), n_constr))
            for row, x in enumerate(X):
                plan = decode(x)
                objectives, _violations = evaluate(plan, envelope, dishes)
                f[row] = [objectives[k] for k in OBJECTIVE_NAMES]
                g[row] = constraint_vector(plan, envelope, dishes)
            out["F"] = f
            out["G"] = g

    return _MealPlanProblem()


def _solve_pymoo(envelope, dishes, pop_size: int, n_gen: int, seed: int, slots: int) -> dict:
    t0 = time.perf_counter()
    problem = _build_pymoo_problem(envelope, dishes, slots)
    algorithm = NSGA2(
        pop_size=pop_size,
        sampling=IntegerRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
        eliminate_duplicates=True,
    )
    res = minimize(problem, algorithm, ("n_gen", n_gen), seed=seed, verbose=False)
    runtime = (time.perf_counter() - t0) * 1000.0

    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    X = res.X
    if X is None:
        return baselines._make_result("pymoo", [], envelope, dishes, 0, runtime)
    X = np.atleast_2d(X)

    front_entries: list[dict] = []
    for x in X:
        plan = [[pool[int(i)]] for i in x]
        objectives, violations = evaluate(plan, envelope, dishes)
        front_entries.append(
            {
                "plan": plan,
                "objectives": objectives,
                "violation_count": len(violations),
                "feasible": len(violations) == 0,
            }
        )

    feasible = [e for e in front_entries if e["feasible"]]
    if feasible:
        best = min(feasible, key=lambda e: baselines.scalar_score(e["objectives"]))
    elif front_entries:
        best = min(
            front_entries,
            key=lambda e: (e["violation_count"], baselines.scalar_score(e["objectives"])),
        )
    else:
        best = None

    if best is None:
        return baselines._make_result("pymoo", [], envelope, dishes, 0, runtime)
    return baselines._make_result(
        "pymoo",
        best["plan"],
        envelope,
        dishes,
        len(front_entries),
        runtime,
        front=front_entries,
        front_size=len(front_entries),
    )


def save_csv(result: dict, path: str = CSV_PATH) -> str:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["rank"] + list(OBJECTIVE_NAMES) + ["violation_count", "feasible"])
        front = result.get("front") or []
        if not front and result.get("plan"):
            front = [
                {
                    "objectives": result["objectives"],
                    "violation_count": result["violation_count"],
                    "feasible": result["feasible"],
                }
            ]
        for rank, entry in enumerate(front):
            objectives = entry["objectives"]
            writer.writerow(
                [rank]
                + [f"{objectives[k]:.6f}" for k in OBJECTIVE_NAMES]
                + [entry["violation_count"], int(bool(entry["feasible"]))]
            )
    return path


def format_plan(plan: list[list[str]], dishes) -> str:
    lookup = dish_lookup(dishes)
    totals = daily_totals(plan, dishes)
    lines = []
    for day, day_total in enumerate(totals):
        meals = plan[day * MEALS_PER_DAY : (day + 1) * MEALS_PER_DAY]
        names = " | ".join(
            "+".join(lookup[d].name for d in meal if d in lookup) for meal in meals
        )
        lines.append(
            f"  Day {day + 1}: {names}"
            f"  [E={day_total['energy_kcal']:.0f} kcal, "
            f"P={day_total['protein_g']:.0f} g, "
            f"Na={day_total['sodium_mg']:.0f} mg]"
        )
    return "\n".join(lines)


def run_spike(
    use_pymoo: bool | None = None,
    pop_size: int = 40,
    n_gen: int = 80,
    seed: int = 42,
    save_csv_file: bool = True,
) -> dict:
    """Run the spike and return the result dict (also used by the smoke test)."""
    if use_pymoo is None:
        use_pymoo = HAS_PYMOO

    envelope = build_sample_envelope()
    dishes = TOY_DISHES
    allowed = allowed_dishes(envelope, dishes)

    if use_pymoo and HAS_PYMOO:
        result = _solve_pymoo(envelope, dishes, pop_size, n_gen, seed, DAYS * MEALS_PER_DAY)
        result["engine"] = "pymoo"
    else:
        result = baselines.nsga2_fallback(
            envelope, dishes, pop_size=pop_size, n_gen=n_gen, seed=seed
        )
        result["engine"] = "fallback-nsga2"
    result["allowed_dish_count"] = len(allowed)
    result["requested_engine"] = "pymoo" if use_pymoo else "fallback-nsga2"
    if save_csv_file:
        result["csv_path"] = save_csv(result)
    return result


def main() -> int:
    result = run_spike()

    print("=" * 74)
    print("CareLoop optimiser spike — toy 8-dish pool, 7 days x 3 meals")
    print("=" * 74)
    print(f"Engine                : {result['engine']}")
    if not HAS_PYMOO:
        print(f"pymoo unavailable     : {PYMOO_IMPORT_ERROR}")
        print("                         -> using pure-Python NSGA-II fallback")
    print(f"Allowed dishes        : {result['allowed_dish_count']} of {len(TOY_DISHES)}")
    print(f"Evaluations           : {result['evaluations']}")
    print("-" * 74)
    print(f"(a) Pareto front size : {result['front_size']}")
    print("(b) Best plan         :")
    print(format_plan(result["plan"], TOY_DISHES))
    objectives = result["objectives"]
    print(
        "    objectives         : "
        + ", ".join(f"{k}={objectives[k]:.3f}" for k in OBJECTIVE_NAMES)
    )
    print(f"(c) Constraint violations: {result['violation_count']}")
    print(f"(d) Runtime           : {result['runtime_ms']:.1f} ms")
    if result.get("csv_path"):
        print(f"CSV                   : {result['csv_path']}")
    print("-" * 74)

    if result["front_size"] == 0:
        print("WARNING: N=0 feasible plans — the toy problem is over-constrained.")
        return 2
    if result["violation_count"] != 0:
        print("FAIL: best plan violates hard constraints.")
        return 1
    print("OK: feasible plan found with 0 hard-constraint violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
