# CareLoop Notebooks

Exploratory analysis and one-off data/rule validation. Notebooks are not part of
the runtime; anything reusable gets promoted into `backend/app/`, `rules/` or
`data/`.

```bash
.venv/bin/python rules/engine.py                    # rule-engine smoke run
.venv/bin/python -m backend.optim.spike_pymoo   # optimiser spike
.venv/bin/python -m pytest rules/ backend -q        # full test suites
```
