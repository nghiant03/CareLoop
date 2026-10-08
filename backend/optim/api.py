"""Backend API adapter (orchestrator-level).

Bridges Lane B's ``backend.optim.spike_pymoo`` (which exposes `run_spike`)
to the contract Lane D's ``/plans`` endpoint expects (`run` / `optimise`).

This module is the contract glue between Lane B and Lane D. Lane B owns
`backend.optim.problem`, `backend.optim.real_data`, and `backend.optim.solver`;
this file lives in the same package so the FastAPI router can probe once
for ``backend.optim.api`` and call ``run(envelope, dishes)``.

Since Week 2 the default dish pool is the real 190-dish dataset in
``data/dishes.json`` (loaded via ``real_data.load_dishes``).
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
    envelope end-to-end.  Week 2: the default pool is the real 190-dish
    ``data/dishes.json`` dataset (``real_data.load_dishes``); the toy pool is
    still available by passing ``dishes=TOY_DISHES`` explicitly.

    ``selection`` is an optional front-selection strategy
    (``(entries, envelope, dishes) -> entry``, see ``backend.optim.selection``)
    passed through to ``solver.solve``; ``None`` keeps the default
    scalar-score selection.

    Hard guarantee: the returned plan NEVER violates the envelope's hard
    constraints (``violation_count == 0``, ``feasible is True``).  If the
    NSGA-II front has no feasible member the best candidate is repaired;
    failing that a greedy-constructed feasible plan is returned.  When the
    allowed pool provably cannot satisfy the envelope the result is an explicit
    infeasibility diagnosis (``feasible=False`` + ``infeasibility_reason``),
    now carrying ``infeasibility_status`` (``"proven_infeasible"`` vs
    ``"search_exhausted"``) from the exact one-day enumeration reference.
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
