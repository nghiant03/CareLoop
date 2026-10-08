"""CareLoop meal optimiser package (Module 4, Lane B — Optimisation).

Public surface:
* :mod:`backend.optim.problem`   — formal problem spec, ``evaluate`` / ``is_feasible``
* :mod:`backend.optim.toy_data`  — Week-1 toy dish pool (Week 2: ``data/dishes.json``)
* :mod:`backend.optim.real_data` — real 214-dish pool, FastEvaluator, feasibility machinery
* :mod:`backend.optim.envelopes` — four representative APPROVED test/benchmark envelopes
* :mod:`backend.optim.solver`    — production ``solve()`` (NSGA-II + feasibility guarantee)
* :mod:`backend.optim.baselines` — random / greedy / exhaustive / NSGA-II fallback
* :mod:`backend.optim.spike_pymoo` — pymoo spike with pure-Python fallback
"""

from __future__ import annotations

from .problem import (
    DAYS,
    MEALS_PER_DAY,
    OBJECTIVE_NAMES,
    SLOTS,
    EnvelopeNotApprovedError,
    allowed_dishes,
    evaluate,
    is_feasible,
)

__all__ = [
    "DAYS",
    "MEALS_PER_DAY",
    "SLOTS",
    "OBJECTIVE_NAMES",
    "EnvelopeNotApprovedError",
    "allowed_dishes",
    "evaluate",
    "is_feasible",
]
