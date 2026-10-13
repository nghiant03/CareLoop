"""Evaluate synthetic fixtures and write ``results.json`` and ``EVALUATION.md``.

Run with ``.venv/bin/python -m evaluation.run``. Fixed-seed metrics depend on
inputs and the numerical environment. Runtime and provenance metadata vary.
"""

from evaluation.run_eval import main

__all__ = ["main"]
