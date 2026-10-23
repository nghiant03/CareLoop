"""Use recorded serving quantities without inferring density or household weights."""

from decimal import Decimal, InvalidOperation


def source_portions(food):
    basis = food.get("basis", "g")
    if basis not in {"g", "ml"}:
        return []
    field, other = ("grams", "millilitres") if basis == "g" else ("millilitres", "grams")
    usable = []
    for portion in food.get("portions", []):
        if portion.get(field) is None or portion.get(other) is not None:
            continue
        try:
            amount = Decimal(str(portion[field]))
        except InvalidOperation:
            continue
        if amount.is_finite() and 0 < amount <= 10000:
            usable.append(portion)
    return usable
