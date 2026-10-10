"""CareLoop automated evaluation suite.

Answers six evaluation questions (traceability, conflict resolution,
constraint satisfaction, quality/runtime, chat groundedness, and selection /
composition ablation) over the repository's synthetic patients and dish catalogue:

* ``evaluation/results.json``  — machine-readable results for all six questions
* ``evaluation/EVALUATION.md`` — human-readable report with tables + limitations

Run::

    .venv/bin/python -m evaluation.run          # or: -m evaluation.run_eval
    .venv/bin/python -m pytest evaluation -q    # harness self-tests

Fixed seeds make numerical results reproducible for unchanged inputs and the
same numerical environment. Wall-clock runtimes vary; provenance metadata also
changes with source revision, source files, interpreter, and platform.
"""

from evaluation.run_eval import main

__all__ = ["main"]
