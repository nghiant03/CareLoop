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

from typing import Callable, Optional

from shared.envelope_schema import EnvelopeStatus, NutrientEnvelope  # noqa: E402

from backend.optim.problem import allowed_dishes  # noqa: E402
from backend.optim.real_data import load_dishes  # noqa: E402
from backend.optim.solver import solve  # noqa: E402


def run(envelope: NutrientEnvelope, dishes=None, seed: int = 42,
        pop_size: int = 40, n_gen: int = 80,
        selection: Optional[Callable] = None) -> dict:
    """Run the optimiser with the given envelope.

    Accepts an injected envelope so the API can pass the clinician-approved
    envelope end-to-end. The default pool is the
    ``data/dishes.json`` dataset (``real_data.load_dishes``); the toy pool is
    still available by passing ``dishes=TOY_DISHES`` explicitly.

    ``selection`` is an optional front-selection strategy
    (``(entries, envelope, dishes) -> entry``, see ``backend.optim.selection``)
    passed through to ``solver.solve``; ``None`` keeps the default
    scalar-score selection.

    Successful plans pass the canonical hard-constraint evaluator. Failure
    returns an empty plan with ``feasible=False`` and a reason. Exact one-day
    enumeration distinguishes ``proven_infeasible`` from ``search_exhausted``
    for this single-dish encoding. This helper checks APPROVED status; the
    application layer additionally enforces scope and nonempty targets.
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
