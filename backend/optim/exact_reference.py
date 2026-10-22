"""Exact reference for single dish days and additive objectives."""

from __future__ import annotations

import math
from itertools import combinations_with_replacement
from typing import Any

import numpy as np

from .problem import (
    EPS,
    MEALS_PER_DAY,
    OBJECTIVE_NAMES,
    SCALAR_WEIGHTS,
    TAG_PREFERENCE,
    ConstraintKind,
    _obj_target_deviation,
    allowed_dishes,
    daily_totals,
    dish_lookup,
)
from .toy_data import NUTRIENT_KEYS, Dish

_ADDITIVE_OBJECTIVES: tuple[str, ...] = (
    "nutrient_target_deviation",
    "preference_sum",
    "cost",
)

_TIE_RTOL = 1e-9

_CHUNK = 20_000


def _tie_tol(a: float, b: float) -> float:
    return _TIE_RTOL * max(1.0, abs(a), abs(b))


def _constraint_cols(envelope) -> tuple[list[tuple[int, float]], list[tuple[int, float]], list[tuple[int, float]]]:
    col = {k: i for i, k in enumerate(NUTRIENT_KEYS)}
    tg: list[tuple[int, float]] = []
    mn: list[tuple[int, float]] = []
    mx: list[tuple[int, float]] = []
    for c in envelope.targets:
        entry = (col[c.nutrient.value], float(c.value))
        if c.kind == ConstraintKind.TARGET:
            tg.append(entry)
        elif c.kind == ConstraintKind.MIN:
            mn.append(entry)
        else:
            mx.append(entry)
    return tg, mn, mx


def _variety_table(lookup_size: int, n_slots: int) -> np.ndarray:
    """Distinct count uniquely determines entropy only for the three slot geometry."""
    denom = math.log(lookup_size) if lookup_size > 1 else 1.0
    ratio_denom = min(lookup_size, n_slots)
    if n_slots != 3:
        raise ValueError("variety table only defined for the 3-slot day geometry")
    entropies = {
        1: 0.0,
        2: -(2 / 3 * math.log(2 / 3) + 1 / 3 * math.log(1 / 3)),
        3: math.log(3.0),
    }
    out = []
    for d in (1, 2, 3):
        norm_entropy = min(1.0, entropies[d] / denom) if denom > 0 else 0.0
        distinct_ratio = d / ratio_denom if ratio_denom else 0.0
        out.append(-(0.5 * norm_entropy + 0.5 * distinct_ratio))
    return np.array(out)


def _empty_result(n_slots: int, pool_size: int) -> dict:
    return {
        "feasible_day": False,
        "feasible_combo_count": 0,
        "pool_size": pool_size,
        "n_slots": n_slots,
        "best": {k: {"dish_ids": [], "value": None} for k in _ADDITIVE_OBJECTIVES},
        "best_scalar": {"dish_ids": [], "value": None},
    }


def _track(best: tuple | None, values: np.ndarray, tuples: list[tuple]) -> tuple | None:
    """Candidate tuples must already be in ascending lexical order."""
    if values.size == 0:
        return best
    vmin = float(values.min())
    if best is None:
        tol = _tie_tol(vmin, vmin)
        pos = int(np.argmax(values <= vmin + tol))
        return (vmin, tuples[pos])
    bval, btup = best
    tol = _tie_tol(vmin, bval)
    if vmin < bval - tol:
        pos = int(np.argmax(values <= vmin + tol))
        return (vmin, tuples[pos])
    if vmin <= bval + tol:
        pos = int(np.argmax(values <= bval + tol))
        cand = tuples[pos]
        if cand < btup:
            return (bval, cand)
    return best


def one_day_exact(envelope, dishes: list[Dish], n_slots: int = MEALS_PER_DAY) -> dict:
    """Enumerate single dish days without proving a full horizon objective optimum."""
    pool = sorted(allowed_dishes(envelope, dishes), key=lambda d: d.dish_id)
    ids = [d.dish_id for d in pool]
    lookup_size = len({d.dish_id for d in dishes})
    result = _empty_result(n_slots, len(pool))
    if not pool or n_slots <= 0:
        return result

    nut = np.array([[d.nutrient(k) for k in NUTRIENT_KEYS] for d in pool], dtype=float)
    pref = np.array([sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in pool], dtype=float)
    price = np.array([d.price_sgd for d in pool], dtype=float)
    tg, mn, mx = _constraint_cols(envelope)
    weight = np.array([SCALAR_WEIGHTS[name] for name in OBJECTIVE_NAMES], dtype=float)

    best_dev: tuple | None = None
    best_pref: tuple | None = None
    best_cost: tuple | None = None
    best_scalar: tuple | None = None
    count = 0

    if n_slots == 3:
        best_dev, best_pref, best_cost, best_scalar, count = _enumerate_three(
            nut, pref, price, tg, mn, mx, weight, lookup_size
        )
    else:
        best_dev, best_pref, best_cost, best_scalar, count = _enumerate_generic(
            nut, pref, price, tg, mn, mx, weight, lookup_size, n_slots
        )

    result["feasible_day"] = count > 0
    result["feasible_combo_count"] = count
    for key, best in (
        ("nutrient_target_deviation", best_dev),
        ("preference_sum", best_pref),
        ("cost", best_cost),
    ):
        if best is not None:
            value, tup = best
            result["best"][key] = {"dish_ids": [ids[i] for i in tup], "value": float(value)}
    if best_scalar is not None:
        value, tup = best_scalar
        result["best_scalar"] = {"dish_ids": [ids[i] for i in tup], "value": float(value)}
    return result


def _enumerate_three(nut, pref, price, tg, mn, mx, weight, lookup_size):
    p = nut.shape[0]
    cols_needed = sorted({col for col, _ in tg} | {col for col, _ in mn} | {col for col, _ in mx})
    pos_in_needed = {col: i for i, col in enumerate(cols_needed)}
    nn = nut[:, cols_needed]

    ii, jj = np.triu_indices(p)  # Upper triangle order is lexicographic.
    pair_n = nn[ii] + nn[jj]
    pair_pref = (pref[:, None] + pref[None, :])[ii, jj]
    pair_price = (price[:, None] + price[None, :])[ii, jj]
    eq_ij = ii == jj

    max_cols = [(pos_in_needed[col], float(v)) for col, v in mx]
    variety_tab = _variety_table(lookup_size, 3)

    best_dev = best_pref = best_cost = best_scalar = None
    count = 0
    for k in range(p):
        feas = jj <= k
        if not feas.any():
            continue
        for cpos, limit in max_cols:
            feas &= pair_n[:, cpos] <= (limit + EPS - nut[k, cols_needed[cpos]])
        idxs = np.flatnonzero(feas)
        if idxs.size == 0:
            continue
        count += idxs.size

        sel_n = pair_n[idxs] + nut[k, cols_needed]
        dev = None
        for col, value in tg:
            term = np.abs(sel_n[:, pos_in_needed[col]] - value)
            dev = term if dev is None else dev + term
        for col, value in mn:
            term = np.maximum(0.0, value - sel_n[:, pos_in_needed[col]])
            dev = term if dev is None else dev + term
        for col, value in mx:
            term = np.maximum(0.0, sel_n[:, pos_in_needed[col]] - value)
            dev = term if dev is None else dev + term
        if dev is None:
            dev = np.zeros(idxs.size)

        pref_v = pair_pref[idxs] + pref[k]
        cost_v = pair_price[idxs] + price[k]
        distinct = 1 + (~eq_ij[idxs]).astype(int) + (jj[idxs] != k)
        variety_v = variety_tab[distinct - 1]
        scalar_v = (
            weight[0] * dev
            + weight[1] * (-pref_v / 3.0)
            + weight[2] * variety_v
            + weight[3] * cost_v
        )

        tuples = [(int(ii[t]), int(jj[t]), k) for t in idxs]
        best_dev = _track(best_dev, dev, tuples)
        best_pref = _track(best_pref, pref_v, tuples)
        best_cost = _track(best_cost, cost_v, tuples)
        best_scalar = _track(best_scalar, scalar_v, tuples)
    return best_dev, best_pref, best_cost, best_scalar, count


def _enumerate_generic(nut, pref, price, tg, mn, mx, weight, lookup_size, n_slots):
    p = nut.shape[0]
    cols_needed = sorted({col for col, _ in tg} | {col for col, _ in mn} | {col for col, _ in mx})
    pos_in_needed = {col: i for i, col in enumerate(cols_needed)}
    max_cols = [(pos_in_needed[col], float(v)) for col, v in mx]

    ratio_denom = min(lookup_size, n_slots)
    denom = math.log(lookup_size) if lookup_size > 1 else 1.0

    def entropy_of(counts: list[int]) -> float:
        n = sum(counts)
        return -sum((c / n) * math.log(c / n) for c in counts)

    state: dict[str, Any] = {"dev": None, "pref": None, "cost": None, "scalar": None, "count": 0}

    def _flush(chunk: list[tuple[int, ...]]) -> None:
        if not chunk:
            return
        arr = np.array(chunk, dtype=int)
        totals = nut[arr].sum(axis=1)
        feas = np.ones(len(arr), dtype=bool)
        for col, limit in max_cols:
            feas &= totals[:, col] <= limit + EPS
        idxs = np.flatnonzero(feas)
        if not idxs.size:
            return
        state["count"] += idxs.size
        sub = arr[idxs]
        totals_cols = {col: totals[idxs, col] for col in cols_needed}
        dev = None
        for col, value in tg:
            term = np.abs(totals_cols[col] - value)
            dev = term if dev is None else dev + term
        for col, value in mn:
            term = np.maximum(0.0, value - totals_cols[col])
            dev = term if dev is None else dev + term
        for col, value in mx:
            term = np.maximum(0.0, totals_cols[col] - value)
            dev = term if dev is None else dev + term
        if dev is None:
            dev = np.zeros(idxs.size)
        pref_v = pref[sub].sum(axis=1)
        cost_v = price[sub].sum(axis=1)
        variety_v = np.empty(idxs.size)
        for r, member in enumerate(sub):
            uniq, cnts = np.unique(member, return_counts=True)
            norm_entropy = min(1.0, entropy_of(cnts.tolist()) / denom) if denom > 0 else 0.0
            variety_v[r] = -(0.5 * norm_entropy + 0.5 * len(uniq) / ratio_denom)
        scalar_v = (
            weight[0] * dev
            + weight[1] * (-pref_v / n_slots)
            + weight[2] * variety_v
            + weight[3] * cost_v
        )
        tuples = [tuple(int(x) for x in row) for row in sub]
        state["dev"] = _track(state["dev"], dev, tuples)
        state["pref"] = _track(state["pref"], pref_v, tuples)
        state["cost"] = _track(state["cost"], cost_v, tuples)
        state["scalar"] = _track(state["scalar"], scalar_v, tuples)

    chunk: list[tuple[int, ...]] = []
    for combo in combinations_with_replacement(range(p), n_slots):
        chunk.append(combo)
        if len(chunk) >= _CHUNK:
            _flush(chunk)
            chunk = []
    _flush(chunk)
    return (
        state["dev"],
        state["pref"],
        state["cost"],
        state["scalar"],
        state["count"],
    )


def prove_infeasible(envelope, dishes: list[Dish]) -> bool:
    """No feasible day proves infeasibility only for the single dish encoding."""
    return not one_day_exact(envelope, dishes)["feasible_day"]


def plan_vs_exact(envelope, dishes: list[Dish], plan) -> dict:
    """Additive day bounds exclude horizon variety and broader compositions."""
    if len(plan) % MEALS_PER_DAY != 0:
        raise ValueError(
            f"plan length {len(plan)} is not a multiple of MEALS_PER_DAY={MEALS_PER_DAY}"
        )
    n_days = len(plan) // MEALS_PER_DAY
    lookup = dish_lookup(dishes)
    daily = daily_totals(plan, dishes)
    exact = one_day_exact(envelope, dishes)

    per_day_values: dict[str, list[float]] = {
        "nutrient_target_deviation": [
            _obj_target_deviation([daily[d]], envelope) for d in range(n_days)
        ],
        "preference_sum": [
            sum(
                sum(TAG_PREFERENCE.get(t, 0.0) for t in dish.tags)
                for meal in plan[d * MEALS_PER_DAY : (d + 1) * MEALS_PER_DAY]
                for dish in (lookup[did] for did in meal if did in lookup)
            )
            for d in range(n_days)
        ],
        "cost": [
            sum(
                lookup[did].price_sgd
                for meal in plan[d * MEALS_PER_DAY : (d + 1) * MEALS_PER_DAY]
                for did in meal
                if did in lookup
            )
            for d in range(n_days)
        ],
    }

    notes = {
        "nutrient_target_deviation": (
            "gap = day deviation - exact one-day minimum (suboptimality in the "
            "minimised direction; one-day semantics identical to "
            "problem._obj_target_deviation for a single day)"
        ),
        "preference_sum": (
            "lower-bound semantics: preference_fit = -mean(tag preference), so "
            "the preference-optimal day MAXIMISES this sum; the reported exact "
            "value is the MINIMUM raw sum over feasible days, and the gap "
            "measures distance above that raw-sum lower bound, not preference "
            "suboptimality"
        ),
        "cost": (
            "gap = day cost - exact one-day minimum cost (suboptimality in the "
            "minimised direction)"
        ),
    }

    objectives_out: dict[str, dict] = {}
    for name in _ADDITIVE_OBJECTIVES:
        best = exact["best"][name]["value"]
        entry: dict = {
            "per_day": per_day_values[name],
            "exact_one_day_best": best,
            "note": notes[name],
        }
        if best is None:
            entry["gaps"] = None
            entry["mean_gap"] = None
            entry["seven_day_lower_bound"] = None
        else:
            gaps = [v - best for v in per_day_values[name]]
            entry["gaps"] = gaps
            entry["mean_gap"] = sum(gaps) / n_days if n_days else 0.0
            entry["seven_day_lower_bound"] = 7.0 * float(best)
        objectives_out[name] = entry

    return {
        "n_days": n_days,
        "exact": {
            "feasible_day": exact["feasible_day"],
            "feasible_combo_count": exact["feasible_combo_count"],
            "pool_size": exact["pool_size"],
        },
        "objectives": objectives_out,
        "excluded_objectives": ["variety"],
        "disclosure": (
            "variety is not per-day decomposable (it is defined over the whole "
            "horizon), so no exact per-day optimum or bound is reported for it; "
            "the bounds above cover nutrient_target_deviation, the raw "
            "preference sum and cost only, and must not be presented as an "
            "exact optimum for all four objectives"
        ),
    }


__all__ = [
    "one_day_exact",
    "plan_vs_exact",
    "prove_infeasible",
]
