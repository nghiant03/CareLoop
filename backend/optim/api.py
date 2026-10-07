"""Backend API adapter (orchestrator-level).

Bridges Lane B's ``backend.optim.spike_pymoo`` (which exposes `run_spike`)
to the contract Lane D's ``/plans`` endpoint expects (`run` / `optimise`).

This module is the contract glue between Lane B and Lane D. Lane B owns
`backend.optim.problem`, `backend.optim.baselines`, and `backend.optim.spike_pymoo`;
this file lives in the same package so the FastAPI router can probe once
for ``backend.optim.api`` and call ``run(envelope, dishes)``.

For Week 1 we use the toy dataset embedded in ``backend.optim.toy_data``.
Week 2 will swap to ``data/dishes.json`` once Lane C finishes the real SG
curation and Lane B wires ``load_dishes()`` into the production pool.
"""

from __future__ import annotations

import os
import sys

# Allow direct execution: `python backend/optim/api.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Optional

from shared.envelope_schema import EnvelopeStatus, NutrientEnvelope  # noqa: E402

from backend.optim.problem import allowed_dishes, evaluate  # noqa: E402
from backend.optim.spike_pymoo import (  # noqa: E402
    HAS_PYMOO,
    _solve_pymoo,
    baselines,
)
from backend.optim.toy_data import TOY_DISHES  # noqa: E402


def run(envelope: NutrientEnvelope, dishes=None, seed: int = 42,
        pop_size: int = 40, n_gen: int = 80) -> dict:
    """Run the optimiser with the given envelope.

    Mirrors ``backend.optim.spike_pymoo.run_spike`` but accepts an injected
    envelope, so the API can pass the clinician-approved envelope end-to-end.
    """

    if envelope.status != EnvelopeStatus.APPROVED:
        raise ValueError(
            f"envelope {envelope.envelope_id} is {envelope.status.value}; "
            "API guard should have rejected it before calling run()."
        )

    dishes = dishes if dishes is not None else TOY_DISHES

    slots = 7 * 3  # DAYS * MEALS_PER_DAY, hard-coded to match spike contract
    allowed = allowed_dishes(envelope, dishes)

    if HAS_PYMOO:
        result = _solve_pymoo(envelope, dishes, pop_size, n_gen, seed, slots)
        result["engine"] = "pymoo"
    else:
        result = baselines.nsga2_fallback(
            envelope, dishes, pop_size=pop_size, n_gen=n_gen, seed=seed,
        )
        result["engine"] = "fallback-nsga2"

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
