"""Experimental USDA nutrient gap estimates requiring recipe and human review.

Estimate missing per-serving potassium/phosphorus from FoodData Central hits.
USDA values are per 100 g. Equal ingredient weight shares substitute for unknown
recipe quantities, so estimates require recipe and portion review before use.

Set ``USDA_API_KEY`` for imports rather than relying on the shared demo key.
Local request budgets do not replace server quotas. Rate limits stop imports,
which retain completed dishes. Search failures and unknown values follow each
helper's contract.

Run: ``python -m backend.datasets.usda_fill_gaps --dishes /external/dishes.json --limit 10``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FDC_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# USDA nutrient identifiers (nutrientId in the FDC API response).
NUTRIENT_ID_POTASSIUM = 1092
NUTRIENT_ID_PHOSPHORUS = 1091

# Use a data.gov key for imports rather than relying on the shared demo quota.
DEFAULT_API_KEY = "DEMO_KEY"

# Default per-budget limit; file imports share one budget across the run.
MAX_REQUESTS_PER_RUN = 30


class RateLimitError(RuntimeError):
    """Raised when the local request budget or the server rate limit is hit."""


@dataclass
class RequestBudget:
    """Track requests made through this instance; share it to bound a whole run."""

    max_requests: int = MAX_REQUESTS_PER_RUN
    used: int = 0
    _last_call_ts: float = field(default=0.0)

    def take(self, min_interval_s: float = 0.0) -> None:
        if self.used >= self.max_requests:
            raise RateLimitError(
                f"local request budget exhausted ({self.used}/{self.max_requests}); "
                "start a new explicitly budgeted run to resume; waiting or changing keys "
                "does not reset this local counter"
            )
        if min_interval_s > 0:
            elapsed = time.monotonic() - self._last_call_ts
            if elapsed < min_interval_s:
                time.sleep(min_interval_s - elapsed)
        self.used += 1
        self._last_call_ts = time.monotonic()


def _http_get_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    """GET ``url`` and decode JSON. Raises RateLimitError on HTTP 429."""
    req = urllib.request.Request(url, headers={"User-Agent": "CareLoop/0.1 (data-pipeline)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitError("USDA FDC returned HTTP 429 (rate limited)") from exc
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise


def search_food(
    query: str,
    api_key: str = DEFAULT_API_KEY,
    page_size: int = 5,
    budget: RequestBudget | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Search FDC for ``query`` and return raw food dicts.

    Returns an empty list for network/HTTP/JSON failures other than HTTP 429.
    Local budget exhaustion and HTTP 429 raise ``RateLimitError``. Malformed
    response shapes or invalid arguments can still raise outside that guard.
    """
    budget = budget or RequestBudget()
    params = urllib.parse.urlencode(
        {
            "api_key": api_key,
            "query": query,
            "pageSize": page_size,
            "dataType": "Foundation,SR Legacy,Survey (FNDDS)",
        }
    )
    url = f"{FDC_SEARCH_URL}?{params}"
    try:
        budget.take()
        payload = _http_get_json(url, timeout=timeout)
    except RateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve unknowns after search failures
        print(f"[usda] search failed for {query!r}: {exc}", file=sys.stderr)
        return []
    return list(payload.get("foods", []) or [])


def _extract_nutrient(food: dict[str, Any], nutrient_id: int) -> float | None:
    """Pull one nutrient value (per 100 g) from an FDC food record."""
    for n in food.get("foodNutrients", []) or []:
        nid = n.get("nutrientId") or n.get("nutrient", {}).get("id")
        if nid == nutrient_id:
            value = n.get("value")
            if value is None:
                value = n.get("amount")
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None
    return None


def estimate_kp_for_ingredient(
    ingredient: str,
    portion_g: float,
    api_key: str = DEFAULT_API_KEY,
    budget: RequestBudget | None = None,
) -> dict[str, Any]:
    """Estimate K/P (mg) for ``portion_g`` of a single ingredient.

    Uses the first FDC hit's per-100 g values scaled by ``portion_g / 100``.
    Returns a dict with ``potassium_mg``/``phosphorus_mg`` (None when unknown),
    the matched description and the fdcId. Missing hits return unknown values;
    rate limits propagate so the run owner can stop. Invalid shapes may raise.
    """
    result: dict[str, Any] = {
        "ingredient": ingredient,
        "portion_g": portion_g,
        "potassium_mg": None,
        "phosphorus_mg": None,
        "usda_match": None,
        "fdc_id": None,
    }
    foods = search_food(ingredient, api_key=api_key, budget=budget)
    if not foods:
        return result

    best = foods[0]
    scale = portion_g / 100.0
    k = _extract_nutrient(best, NUTRIENT_ID_POTASSIUM)
    p = _extract_nutrient(best, NUTRIENT_ID_PHOSPHORUS)
    if k is not None:
        result["potassium_mg"] = round(k * scale, 1)
    if p is not None:
        result["phosphorus_mg"] = round(p * scale, 1)
    result["usda_match"] = best.get("description")
    result["fdc_id"] = best.get("fdcId")
    return result


def estimate_dish_gaps(
    dish: dict[str, Any],
    api_key: str = DEFAULT_API_KEY,
    budget: RequestBudget | None = None,
) -> dict[str, Any]:
    """Estimate missing K/P for one dish from its ingredient list.

    Splits the serving weight equally across ingredients, scales each matched
    per-100 g value, and sums the available estimates. Unknown recipe quantities
    and missing matches can bias results in either direction; keep
    ``provenance='usda_estimate'`` until human review.

    Existing nonzero K/P values are preserved; None and zero count as gaps.
    Returns a shallow copy without mutating ``dish``. Changed estimates clear
    verification. Rate limits propagate and discard this dish's partial estimates;
    invalid inputs or malformed response shapes may raise.
    """
    portion = float(dish.get("portion_g") or 100.0)
    ingredients = dish.get("ingredients") or []
    # Recipe weights are unavailable; equal shares are an estimation assumption.
    per_ingredient_g = portion / max(len(ingredients), 1)

    total_k = 0.0
    total_p = 0.0
    matches: list[str] = []
    got_k = got_p = False
    for ing in ingredients:
        est = estimate_kp_for_ingredient(
            ing, per_ingredient_g, api_key=api_key, budget=budget
        )
        if est["potassium_mg"] is not None:
            total_k += est["potassium_mg"]
            got_k = True
        if est["phosphorus_mg"] is not None:
            total_p += est["phosphorus_mg"]
            got_p = True
        if est["usda_match"]:
            matches.append(f"{ing}->{est['usda_match']}")

    out = dict(dish)
    if got_k and dish.get("potassium_mg") in (None, 0):
        out["potassium_mg"] = round(total_k, 1)
    if got_p and dish.get("phosphorus_mg") in (None, 0):
        out["phosphorus_mg"] = round(total_p, 1)
    if matches:
        out["usda_match"] = "; ".join(matches[:5])
    if out.get("potassium_mg") != dish.get("potassium_mg") or out.get("phosphorus_mg") != dish.get("phosphorus_mg"):
        out["provenance"] = "usda_estimate"
        out["verified"] = False
        # K/P estimates affect nutrient tags, not curated cooking/protein roles.
        tags = list(out.get("tags") or [])
        for tag, nutrient, threshold in (("high_potassium", "potassium_mg", 700),
                                         ("high_phosphorus", "phosphorus_mg", 300)):
            tags = [existing for existing in tags if existing != tag]
            if (out.get(nutrient) or 0) >= threshold:
                tags.append(tag)
        out["tags"] = tags
    return out


def fill_gaps_in_file(
    path: Path,
    api_key: str = DEFAULT_API_KEY,
    limit: int | None = None,
    min_interval_s: float = 0.0,
    budget: RequestBudget | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Load a dishes JSON, estimate K/P for records missing them.

    Returns ``(dishes, n_updated)``. Only dishes with a missing K or P and a
    non-empty ingredient list are candidates. Request budget is shared across the
    whole run. Pass a budget to inspect request usage. On a rate limit, retain
    completed dishes but leave the interrupted and subsequent dishes unchanged.
    """
    dishes = json.loads(path.read_text(encoding="utf-8"))
    budget = budget or RequestBudget(max_requests=MAX_REQUESTS_PER_RUN)
    candidates = [
        d
        for d in dishes
        if (d.get("potassium_mg") in (None, 0) or d.get("phosphorus_mg") in (None, 0))
        and d.get("ingredients")
    ]
    if limit is not None:
        candidates = candidates[:limit]

    updated = 0
    for d in candidates:
        try:
            filled = estimate_dish_gaps(d, api_key=api_key, budget=budget)
        except RateLimitError as exc:
            print(f"[usda] rate limit reached, stopping: {exc}", file=sys.stderr)
            break
        if (
            filled.get("potassium_mg") != d.get("potassium_mg")
            or filled.get("phosphorus_mg") != d.get("phosphorus_mg")
        ):
            d.update(filled)
            updated += 1
        if min_interval_s:
            time.sleep(min_interval_s)
    return dishes, updated


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="USDA FDC K/P gap filler (skeleton).")
    p.add_argument("--ingredient", help="estimate a single ingredient and exit")
    p.add_argument("--portion-g", type=float, default=100.0, help="portion grams (default 100)")
    p.add_argument("--dishes", type=Path, help="dishes JSON to fill gaps in")
    p.add_argument("--out", type=Path, help="where to write filled dishes JSON")
    p.add_argument("--limit", type=int, default=None, help="max dishes to process")
    p.add_argument(
        "--api-key",
        default=os.environ.get("USDA_API_KEY", DEFAULT_API_KEY),
        help="FDC API key (default: $USDA_API_KEY or DEMO_KEY)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    budget = RequestBudget()

    if args.ingredient:
        try:
            est = estimate_kp_for_ingredient(
                args.ingredient, args.portion_g, api_key=args.api_key, budget=budget
            )
        except RateLimitError as exc:
            print(f"[usda] stopping: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(est, indent=2))
        return 0

    if args.dishes:
        dishes, updated = fill_gaps_in_file(
            args.dishes, api_key=args.api_key, limit=args.limit, budget=budget
        )
        out = args.out or args.dishes
        out.write_text(json.dumps(dishes, indent=2) + "\n", encoding="utf-8")
        print(
            f"Updated {updated} dish(es); wrote {out} "
            f"(requests used: {budget.used}/{MAX_REQUESTS_PER_RUN}). "
            "NOTE: DEMO_KEY is rate-limited (~30 req/h)."
        )
        return 0

    _build_parser().print_help()
    print(
        "\nNOTE: DEMO_KEY is rate-limited to ~30 requests/hour; set USDA_API_KEY "
        "for a higher limit. Network/HTTP/JSON failures return unknown estimates; "
        "invalid inputs or malformed response shapes may raise.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
