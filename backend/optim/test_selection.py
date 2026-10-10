"""Deterministic front selection and original-aim scoring tests.

Builds three feasible front entries over a tiny pool where the strategies
PROVABLY disagree:

* entry ``adequate`` — exceeds the protein MIN and meets the energy TARGET
  exactly, but is expensive;
* entry ``cheap``     — well under cost, but misses the protein MIN on every
  day (shortfall 32/60 g);
* entry ``middle``    — meets protein but deviates from the energy TARGET.

Expected winners (hand-checkable):

* ``scalar_selection``  -> ``cheap``   (cost dominates the raw-unit scalar);
* ``normalised_selection``   -> ``adequate`` (zero relative deviation);
* ``adequacy_first_selection`` -> ``adequate`` (zero worst-day shortfall).

Also asserts determinism (repeated calls and reversed entry order agree).

Run with pytest so fixture-dependent tests receive their arguments::

    .venv/bin/python -m pytest backend/optim/test_selection.py
"""

from __future__ import annotations

import os
import sys

# Allow direct execution: `python backend/optim/test_selection.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.envelope_schema import (  # noqa: E402
    ConstraintKind,
    EnvelopeStatus,
    NutrientConstraint,
    NutrientEnvelope,
    NutrientKind,
    PatientSummary,
)

from backend.optim.problem import MEALS_PER_DAY, evaluate  # noqa: E402
from backend.optim.selection import (  # noqa: E402
    adequacy_first_selection,
    normalised_selection,
    scalar_selection,
)
from backend.optim.toy_data import Dish  # noqa: E402


def _dish(did: str, energy: float, protein: float, sodium: float, price: float, tags: tuple) -> Dish:
    return Dish(
        dish_id=did,
        name=did,
        category="test",
        nutrients={"energy_kcal": energy, "protein_g": protein, "sodium_mg": sodium},
        tags=tags,
        price_sgd=price,
    )


SELECTION_POOL: list[Dish] = [
    _dish("protein_plate", 600, 30, 400, 8.0, ("lean_protein", "low_sodium")),
    _dish("veg_plate", 400, 8, 300, 3.0, ("vegetable", "high_fiber")),
    _dish("cheap_rice", 700, 10, 500, 2.0, ("moderate_sodium",)),
]


def _envelope():
    return NutrientEnvelope(
        envelope_id="env-selection-test",
        patient_id="p-selection",
        status=EnvelopeStatus.APPROVED,
        version=1,
        patient_snapshot=PatientSummary(
            patient_id="p-selection", age=50, sex="F", weight_kg=60, diagnoses=[]
        ),
        targets=[
            NutrientConstraint(nutrient=NutrientKind.PROTEIN_G, kind=ConstraintKind.MIN, value=60.0, unit="g"),
            NutrientConstraint(nutrient=NutrientKind.SODIUM_MG, kind=ConstraintKind.MAX, value=2000.0, unit="mg"),
            NutrientConstraint(nutrient=NutrientKind.ENERGY_KCAL, kind=ConstraintKind.TARGET, value=1800.0, unit="kcal"),
        ],
        exclusions=[],
        priority_basis="test",
    )


def _day(dish_ids: list[str]) -> list[list[str]]:
    """One day of single-dish slots from a 3-dish multiset."""
    return [[did] for did in dish_ids]


def _entries() -> list[dict]:
    env = _envelope()
    specs = {
        # protein 90 >= 60, energy 1800 == TARGET, sodium 1200 <= 2000; 3 x 8.0
        "adequate": ["protein_plate", "protein_plate", "protein_plate"],
        # protein 28 (short 32), energy 1800, sodium 1300; 2 x 2.0 + 3.0
        "cheap": ["cheap_rice", "cheap_rice", "veg_plate"],
        # protein 68, energy 1600 (dev 200), sodium 1100; 2 x 8.0 + 3.0
        "middle": ["protein_plate", "protein_plate", "veg_plate"],
    }
    entries = []
    for name, multiset in specs.items():
        day = _day(multiset)
        plan = day * 7
        objectives, violations = evaluate(plan, env, SELECTION_POOL)
        assert not violations, (name, violations)
        entries.append(
            {
                "name": name,
                "plan": plan,
                "objectives": objectives,
                "violations": violations,
                "violation_count": len(violations),
                "feasible": True,
            }
        )
    return entries


def _by_name(entry: dict) -> str:
    return entry["name"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_scalar_selection_prefers_the_cheap_entry():
    entries = _entries()
    picked = scalar_selection(entries, _envelope(), SELECTION_POOL)
    assert _by_name(picked) == "cheap"


def test_normalised_selection_prefers_the_adequate_entry():
    entries = _entries()
    picked = normalised_selection(entries, _envelope(), SELECTION_POOL)
    assert _by_name(picked) == "adequate"


def test_adequacy_first_selection_prefers_the_adequate_entry():
    entries = _entries()
    picked = adequacy_first_selection(entries, _envelope(), SELECTION_POOL)
    assert _by_name(picked) == "adequate"


def test_strategies_are_deterministic_and_order_independent():
    env = _envelope()
    entries = _entries()
    for strategy in (scalar_selection, normalised_selection, adequacy_first_selection):
        first = strategy(entries, env, SELECTION_POOL)
        again = strategy(entries, env, SELECTION_POOL)
        assert first is again or first == again
        reversed_pick = strategy(list(reversed(entries)), env, SELECTION_POOL)
        assert _by_name(reversed_pick) == _by_name(first), strategy.__name__


def test_all_strategies_return_a_front_entry():
    entries = _entries()
    env = _envelope()
    for strategy in (scalar_selection, normalised_selection, adequacy_first_selection):
        assert strategy(entries, env, SELECTION_POOL) in entries


def test_solve_selection_kwarg_overrides_default_scalar_choice(monkeypatch):
    """solve(selection=...) must actually change the delivered plan: with the
    same two-entry front, the default picks 'cheap' while the normalised
    strategy picks 'adequate'."""
    import numpy as np

    import backend.optim.solver as solver_mod

    env = _envelope()
    # FastEvaluator pool order = SELECTION_POOL order:
    # protein_plate=0, veg_plate=1, cheap_rice=2
    cheap_idx = np.array(([2, 2, 1] * 7), dtype=int)      # 'cheap' entry
    adequate_idx = np.array(([0, 0, 0] * 7), dtype=int)   # 'adequate' entry
    monkeypatch.setattr(solver_mod, "HAS_PYMOO", True)
    monkeypatch.setattr(
        solver_mod,
        "_pymoo_front",
        lambda ev, seed, pop, gen, method="nsga2": [cheap_idx, adequate_idx],
    )

    default_result = solver_mod.solve(env, SELECTION_POOL, seed=1, pop_size=8, n_gen=4)
    assert default_result["feasible"] is True
    assert default_result["plan"] == ev_idx_to_plan_local(cheap_idx, SELECTION_POOL)

    picked = solver_mod.solve(
        env, SELECTION_POOL, seed=1, pop_size=8, n_gen=4,
        selection=normalised_selection,
    )
    assert picked["feasible"] is True
    assert picked["plan"] == ev_idx_to_plan_local(adequate_idx, SELECTION_POOL)


def ev_idx_to_plan_local(idx, dishes) -> list[list[str]]:
    """Helper mirroring FastEvaluator.idx_to_plan (original pool order)."""
    pool_ids = [d.dish_id for d in dishes]
    return [[pool_ids[int(i)]] for i in idx]


def test_adequacy_key_ranks_shortfall_then_count_then_scalar():
    from dataclasses import replace

    env = _envelope()
    entries = _entries()
    by_name = {e["name"]: e for e in entries}
    # hand-checked lexicographic keys: adequate (0,0,...) < middle (0.111,7,..)
    # < cheap (0.533,7,...) — worst-day shortfall dominates unmet count.
    picked = adequacy_first_selection(
        [by_name["cheap"], by_name["middle"], by_name["adequate"]], env, SELECTION_POOL
    )
    assert _by_name(picked) == "adequate"
    picked = adequacy_first_selection([by_name["cheap"], by_name["middle"]], env, SELECTION_POOL)
    assert _by_name(picked) == "middle"

    # Same worst deviation, but only one day misses energy instead of seven.
    fewer_unmet = {"plan": by_name["middle"]["plan"][:3] + by_name["adequate"]["plan"][3:]}
    fewer_unmet["objectives"], violations = evaluate(fewer_unmet["plan"], env, SELECTION_POOL)
    assert not violations
    assert adequacy_first_selection([by_name["middle"], fewer_unmet], env, SELECTION_POOL) is fewer_unmet

    # Equal worst deviation and unmet count: cheaper equivalent dishes win.
    discounted = replace(SELECTION_POOL[0], dish_id="discount_protein", price_sgd=0)
    pool = SELECTION_POOL + [discounted]
    cheaper = {"plan": [["discount_protein" if did == "protein_plate" else did for did in meal]
                        for meal in by_name["middle"]["plan"]]}
    cheaper["objectives"], violations = evaluate(cheaper["plan"], env, pool)
    assert not violations
    assert adequacy_first_selection([by_name["middle"], cheaper], env, pool) is cheaper


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run .venv/bin/python -m pytest backend/optim/test_selection.py")
