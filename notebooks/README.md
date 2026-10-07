# CareLoop Notebooks

Exploratory analysis and one-off data/rule validation. Notebooks are not part of
the runtime; anything reusable gets promoted into `backend/app/`, `rules/` or
`data/`.

- `exploration_01_overview.ipynb` — orientation notebook (markdown): schema,
  rule priorities, data sources, and the end-to-end contract.

Useful executable counterparts outside the notebook:

```bash
.venv/bin/python rules/engine.py                    # rule-engine smoke run
PYTHONPATH=. .venv/bin/python -m backend.optim.spike_pymoo   # optimiser spike
.venv/bin/python -m pytest rules/ backend -q        # full test suites
```
