"""Single-dish solver entry point with patient/envelope result metadata.

Uses ``solver.solve`` and the catalogue in ``data/dishes.json`` by default.
Application planning adds main/side composition through ``plan_service.plan_meals``.
"""

from __future__ import annotations

import os
import sys

# Allow direct execution: `python backend/optim/api.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from collections.abc import Callable

from backend.optim.problem import allowed_dishes
from backend.optim.real_data import load_dishes
from backend.optim.solver import solve
from shared.envelope_schema import EnvelopeStatus, NutrientEnvelope


def run(envelope: NutrientEnvelope, dishes=None, seed: int = 42,
        pop_size: int = 40, n_gen: int = 80,
        selection: Callable | None = None) -> dict:
    """Solve an APPROVED envelope, using catalogue dishes unless supplied.

    ``selection`` follows ``solver.solve``'s callback contract. None uses
    scalar scoring. Success passes canonical hard checks. Failure returns an
    empty plan with a reason and single-dish infeasibility diagnosis.
    Application callers must also enforce scope eligibility and target readiness.
    """

    if envelope.status != EnvelopeStatus.APPROVED:
        raise ValueError(
            f"envelope {envelope.envelope_id} is {envelope.status.value}; "
            "API guard should have rejected it before calling run()."
        )

    if dishes is None:
        dishes = load_dishes()

    allowed = allowed_dishes(envelope, dishes)

    result = solve(
        envelope, dishes, seed=seed, pop_size=pop_size, n_gen=n_gen, method="nsga2",
        selection=selection,
    )
    result["envelope_id"] = envelope.envelope_id
    result["patient_id"] = envelope.patient_id
    result["allowed_dish_count"] = len(allowed)
    return result


def optimise(envelope: NutrientEnvelope, dishes=None, **kwargs) -> dict:
    """Alias for symmetry with `run` — same semantic."""
    return run(envelope, dishes=dishes, **kwargs)


if __name__ == "__main__":  # pragma: no cover
    import json

    from backend.optim.spike_pymoo import build_sample_envelope

    result = run(build_sample_envelope())
    print(json.dumps(
        {
            "engine": result["engine"],
            "front_size": result["front_size"],
            "violation_count": result["violation_count"],
            "runtime_ms": result["runtime_ms"],
            "objectives": result["objectives"],
            "feasible": result["feasible"],
        },
        indent=2,
    ))
