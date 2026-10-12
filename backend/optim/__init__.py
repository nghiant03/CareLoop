"""Meal search, canonical evaluation, and benchmark reference implementations.

Public surface:
* :mod:`backend.optim.problem`   — formal problem spec, ``evaluate`` / ``is_feasible``
* :mod:`backend.optim.toy_data`  — dish contract and self-contained test pool
* :mod:`backend.optim.real_data` — catalogue loader, vector evaluation, repair heuristics
* :mod:`backend.optim.envelopes` — four representative APPROVED test/benchmark envelopes
* :mod:`backend.optim.solver`    — single-dish search with validated results or diagnosis
* :mod:`backend.optim.composition` — main/optional-side search against original aims
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
    "OBJECTIVE_NAMES",
    "SLOTS",
    "EnvelopeNotApprovedError",
    "allowed_dishes",
    "evaluate",
    "is_feasible",
]
