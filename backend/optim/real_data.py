"""Catalogue loading and vectorized single dish evaluation."""

from __future__ import annotations

import json
import math
import os
import random
from functools import lru_cache

import numpy as np

from backend.knowledge.runtime import selected_release

from .problem import (
    DAYS,
    EPS,
    MEALS_PER_DAY,
    NUTRIENT_KEYS,
    OBJECTIVE_NAMES,
    SCALAR_WEIGHTS,
    TAG_PREFERENCE,
    ConstraintKind,
    allowed_dishes,
)
from .toy_data import Dish

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.datasets.paths import dataset_path

DEFAULT_DISHES_PATH = str(dataset_path("dishes.json"))

# Match the canonical scalar objective ordering.
_SCALAR_WEIGHT_VEC = np.array(
    [SCALAR_WEIGHTS[name] for name in OBJECTIVE_NAMES], dtype=float
)


def _synthetic_price(row: dict) -> float:
    """Missing prices use an energy and protein proxy."""
    energy = float(row.get("energy_kcal", 0.0) or 0.0)
    protein = float(row.get("protein_g", 0.0) or 0.0)
    return round(2.5 + 0.004 * energy + 0.02 * protein, 2)


@lru_cache(maxsize=8)
def _load_cached(path: str, release_json: str | None = None) -> tuple[Dish, ...]:
    if release_json is None:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        raw = json.loads(release_json)
    dishes: list[Dish] = []
    for row in raw:
        nutrients = {k: float(row.get(k, 0.0) or 0.0) for k in NUTRIENT_KEYS}
        dishes.append(
            Dish(
                dish_id=str(row["dish_id"]),
                name=row.get("name", str(row["dish_id"])),
                category=row.get("category", "unknown"),
                nutrients=nutrients,
                ingredients=tuple(row.get("ingredients", ()) or ()),
                tags=tuple(row.get("tags", ()) or ()),
                price_sgd=float(row.get("price_sgd", _synthetic_price(row))),
                price_is_estimated="price_sgd" not in row,
                verified=bool(row.get("verified", False)),
            )
        )
    return tuple(dishes)


def load_dishes(path: str | None = None) -> list[Dish]:
    if path is None:
        release = selected_release()
        if release is not None:
            return list(_load_cached(f"release:{release.release_id}", release.dishes_json))
        path = DEFAULT_DISHES_PATH
    return list(_load_cached(os.path.abspath(path)))


class FastEvaluator:
    """Indices address the allowed pool. Callers enforce approval and structural validity."""

    def __init__(self, envelope, dishes: list[Dish], n_days: int = DAYS):
        self.envelope = envelope
        self.dishes = dishes
        self.n_days = n_days
        self.slots = n_days * MEALS_PER_DAY

        pool = allowed_dishes(envelope, dishes)
        self.pool_ids: list[str] = [d.dish_id for d in pool]
        self.size = len(pool)
        self.full_size = len(dishes)

        col = {k: i for i, k in enumerate(NUTRIENT_KEYS)}
        self._targets = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets
            if c.kind == ConstraintKind.TARGET
        ]
        self._max_daily = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets
            if c.kind == ConstraintKind.MAX
        ]
        self._min_daily = [
            (col[c.nutrient.value], float(c.value))
            for c in envelope.targets
            if c.kind == ConstraintKind.MIN
        ]
        self.n_constraints = len(self._max_daily) * (n_days + 1)

        if self.size:
            self._nut = np.array(
                [[d.nutrient(k) for k in NUTRIENT_KEYS] for d in pool], dtype=float
            )
            self._pref = np.array(
                [sum(TAG_PREFERENCE.get(t, 0.0) for t in d.tags) for d in pool],
                dtype=float,
            )
            self._price = np.array([d.price_sgd for d in pool], dtype=float)
            self._col_max = self._nut.max(axis=0)
        else:
            self._nut = np.zeros((0, len(NUTRIENT_KEYS)))
            self._pref = np.zeros(0)
            self._price = np.zeros(0)
            self._col_max = np.zeros(len(NUTRIENT_KEYS))

    def plan_to_idx(self, plan: list[list[str]]) -> np.ndarray:
        pos = {did: i for i, did in enumerate(self.pool_ids)}
        flat = [d for meal in plan for d in meal]
        if len(flat) != self.slots:
            raise ValueError(f"plan has {len(flat)} slots, expected {self.slots}")
        missing = [d for d in flat if d not in pos]
        if missing:
            raise KeyError(f"dishes outside the allowed pool: {missing[:5]}")
        return np.array([pos[d] for d in flat], dtype=int)

    def idx_to_plan(self, idx) -> list[list[str]]:
        return [[self.pool_ids[int(i)]] for i in idx]

    def daily_totals(self, idx: np.ndarray) -> np.ndarray:
        idx = np.asarray(idx, dtype=int)
        return self._nut[idx].reshape(self.n_days, MEALS_PER_DAY, -1).sum(axis=1)

    def f_vector(self, idx: np.ndarray, daily: np.ndarray | None = None) -> np.ndarray:
        if daily is None:
            daily = self.daily_totals(idx)
        idx = np.asarray(idx, dtype=int)

        dev = 0.0
        for col, value in self._targets:
            dev += float(np.abs(daily[:, col] - value).sum())
        for col, value in self._min_daily:
            dev += float(np.maximum(0.0, value - daily[:, col]).sum())
        for col, value in self._max_daily:
            dev += float(np.maximum(0.0, daily[:, col] - value).sum())
        deviation = dev / self.n_days if self.n_days else 0.0

        n = idx.size
        preference = -float(self._pref[idx].mean()) if n else 0.0

        if n:
            counts = np.bincount(idx, minlength=self.size)
            nz = counts[counts > 0].astype(float)
            probs = nz / n
            entropy = float(-(probs * np.log(probs)).sum())
            denom = math.log(self.full_size) if self.full_size > 1 else 1.0
            norm_entropy = min(1.0, entropy / denom) if denom > 0 else 0.0
            distinct_ratio = int((counts > 0).sum()) / min(self.full_size, n)
            variety = -(0.5 * norm_entropy + 0.5 * distinct_ratio)
        else:
            variety = 0.0

        cost = float(self._price[idx].sum()) if n else 0.0

        return np.array([deviation, preference, variety, cost])

    def g_vector(self, daily: np.ndarray) -> np.ndarray:
        parts: list[np.ndarray] = []
        for col, limit in self._max_daily:
            over = np.maximum(0.0, daily[:, col] - limit) - EPS
            parts.append(over)
            horizon = float(daily[:, col].sum())
            parts.append(
                np.array([max(0.0, horizon - limit * self.n_days) - EPS])
            )
        if not parts:
            return np.zeros(0)
        return np.concatenate(parts)

    def eval_indices(self, idx) -> tuple[np.ndarray, np.ndarray]:
        idx = np.asarray(idx, dtype=int)
        daily = self.daily_totals(idx)
        return self.f_vector(idx, daily), self.g_vector(daily)

    def eval_batch(self, X) -> tuple[np.ndarray, np.ndarray]:
        X = np.atleast_2d(np.asarray(X, dtype=int))
        F = np.zeros((len(X), len(OBJECTIVE_NAMES)))
        G = np.zeros((len(X), self.n_constraints))
        for r, x in enumerate(X):
            F[r], G[r] = self.eval_indices(x)
        return F, G

    def scalar(self, f: np.ndarray) -> float:
        return float(_SCALAR_WEIGHT_VEC @ f)

    def day_violation(self, totals: np.ndarray) -> tuple[int, float]:
        count = 0
        mag = 0.0
        for col, limit in self._max_daily:
            over = totals[col] - limit
            if over > EPS:
                count += 1
                mag += over
        return count, mag


def feasibility_precheck(envelope, dishes: list[Dish], n_days: int = DAYS):
    """Passing is necessary but not sufficient for single dish feasibility."""
    pool = allowed_dishes(envelope, dishes)
    if not pool:
        return False, "exclusions remove every dish from the pool (0 allowed dishes)"
    col = {k: i for i, k in enumerate(NUTRIENT_KEYS)}
    nut = np.array([[d.nutrient(k) for k in NUTRIENT_KEYS] for d in pool])
    for c in envelope.targets:
        key = c.nutrient.value
        values = nut[:, col[key]]
        if c.kind == ConstraintKind.MAX:
            least = 3.0 * float(values.min())
            if least > float(c.value) + EPS:
                return False, (
                    f"hard MAX {key} <= {c.value} impossible: the three lowest-{key} "
                    f"dishes still total {least:.1f} per day"
                )
    return True, None


def _greedy_pick_day(
    ev: FastEvaluator,
    used: dict[int, int] | None = None,
    rng: random.Random | None = None,
) -> np.ndarray:
    used = used or {}
    running = np.zeros(ev._nut.shape[1])
    chosen: list[int] = []
    for slot in range(MEALS_PER_DAY):
        best_j = None
        best_score = None
        for j in range(ev.size):
            trial = running + ev._nut[j]
            score = 0.0
            for col, limit in ev._max_daily:
                over = trial[col] - limit
                if over > 0:
                    score += 10.0 * over
                else:
                    score += 0.02 * trial[col] / max(limit, 1.0)
            remaining = MEALS_PER_DAY - (slot + 1)
            for col, limit in ev._min_daily:
                best_possible = trial[col] + remaining * ev._col_max[col]
                if best_possible < limit:
                    score += 5.0 * (limit - best_possible)
            score += 0.05 * ev._price[j]
            score += 0.2 * (-ev._pref[j])
            score += 0.15 * used.get(j, 0)
            if rng is not None and rng.random() < 0.05:
                score += rng.random() * 0.1
            if best_score is None or score < best_score:
                best_score = score
                best_j = j
        if best_j is None:
            raise ValueError("cannot choose a meal from an empty dish pool")
        chosen.append(best_j)
        running = running + ev._nut[best_j]
        used[best_j] = used.get(best_j, 0) + 1
    return np.array(chosen, dtype=int)


def _repair_day(ev: FastEvaluator, day_idx: np.ndarray, max_passes: int = 6):
    day_idx = day_idx.copy()
    totals = ev._nut[day_idx].sum(axis=0)
    count, mag = ev.day_violation(totals)
    key = (count, mag, float(ev._price[day_idx].sum()))
    if count == 0:
        return day_idx
    for _ in range(max_passes):
        improved = False
        for slot in range(MEALS_PER_DAY):
            for j in range(ev.size):
                if j == day_idx[slot]:
                    continue
                trial = day_idx.copy()
                trial[slot] = j
                t = ev._nut[trial].sum(axis=0)
                c2, m2 = ev.day_violation(t)
                k2 = (c2, m2, float(ev._price[trial].sum()))
                if k2 < key:
                    day_idx = trial
                    key = k2
                    improved = True
                    if c2 == 0:
                        return day_idx
        if not improved:
            break
    return day_idx


def _build_feasible_day(
    ev: FastEvaluator, seed: int, day: int, used: dict[int, int]
) -> np.ndarray | None:
    """Success updates usage counts. Failure leaves them unchanged and proves nothing."""
    rng = random.Random((seed * 1_000_003 + day * 97 + 13) & 0xFFFFFFFF)
    day_idx = _greedy_pick_day(ev, used=dict(used), rng=rng)
    count, _mag = ev.day_violation(ev._nut[day_idx].sum(axis=0))
    if count:
        day_idx = _repair_day(ev, day_idx)
        count, _mag = ev.day_violation(ev._nut[day_idx].sum(axis=0))
    if count:
        return None
    for j in day_idx:
        used[j] = used.get(j, 0) + 1
    return day_idx


def greedy_feasible_plan(ev: FastEvaluator, seed: int = 0) -> np.ndarray | None:
    """Daily tolerance can accumulate beyond the horizon tolerance. Validate the full candidate before delivery."""
    used: dict[int, int] = {}
    days: list[np.ndarray] = []
    for day in range(ev.n_days):
        day_idx = _build_feasible_day(ev, seed, day, used)
        if day_idx is None:
            for attempt in range(3):
                day_idx = _build_feasible_day(ev, seed + 101 * (attempt + 1), day, used)
                if day_idx is not None:
                    break
        if day_idx is None:
            return None
        days.append(day_idx)
    return np.concatenate(days)


def repair_plan(
    ev: FastEvaluator, idx: np.ndarray, seed: int = 0
) -> np.ndarray | None:
    """Return a repaired copy or no candidate. Heuristic failure is not an infeasibility proof."""
    idx = np.asarray(idx, dtype=int).copy()
    used: dict[int, int] = {}
    for i in idx:
        used[int(i)] = used.get(int(i), 0) + 1
    for day in range(ev.n_days):
        lo, hi = day * MEALS_PER_DAY, (day + 1) * MEALS_PER_DAY
        day_idx = idx[lo:hi]
        count, _mag = ev.day_violation(ev._nut[day_idx].sum(axis=0))
        if count:
            day_idx = _repair_day(ev, day_idx)
            count, _mag = ev.day_violation(ev._nut[day_idx].sum(axis=0))
        if count:
            day_idx = _build_feasible_day(ev, seed, day, used)
            if day_idx is None:
                return None
        idx[lo:hi] = day_idx
    return idx


__all__ = [
    "DEFAULT_DISHES_PATH",
    "FastEvaluator",
    "feasibility_precheck",
    "greedy_feasible_plan",
    "load_dishes",
    "repair_plan",
]
