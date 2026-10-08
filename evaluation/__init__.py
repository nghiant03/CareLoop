"""CareLoop automated evaluation suite.

Answers six evaluation questions (traceability, conflict resolution,
constraint satisfaction, quality/runtime, chat groundedness, and selection /
composition ablation) over the real
patients/rules/dishes and produces a reproducible report:

* ``evaluation/results.json``  — machine-readable results for all six questions
* ``evaluation/EVALUATION.md`` — human-readable report with tables + limitations

Run::

    .venv/bin/python -m evaluation.run          # or: -m evaluation.run_eval
    .venv/bin/python -m pytest evaluation -q    # harness self-tests

Deterministic: fixed seeds everywhere; the rule engine and optimiser are
deterministic given a seed. The only non-deterministic fields are wall-clock
runtimes (clearly marked as such).
"""

from evaluation.run_eval import main

__all__ = ["main"]
