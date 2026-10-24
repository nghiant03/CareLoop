"""Versioned, conditional starting estimate; never an approved target."""

from decimal import ROUND_HALF_UP, Decimal

SOURCE = "https://www.nice.org.uk/guidance/cg32/chapter/Recommendations#what-to-give-in-hospital-and-the-community"
QUOTE = (
    "For people who are not severely ill or injured, nor at risk of refeeding syndrome, "
    "the suggested nutritional prescription for total intake should provide all of the following: "
    "25 to 35 kcal/kg/day total energy (including that derived from protein); this level may "
    "need to be lower in people who are overweight, with a BMI over 25."
)


def energy_proposal(facts):
    result = {
        "method": "nice-cg32-1.4.2-v2",
        "source": SOURCE,
        "source_title": "NICE CG32, recommendation 1.4.2",
        "quote": QUOTE,
        "inputs": {
            k: facts.get(k)
            for k in (
                "age_years",
                "weight_kg",
                "height_cm",
                "observed_on",
                "pregnant",
                "breastfeeding",
                "dialysis",
                "has_ckd",
                "conditions",
            )
        },
        "review": [
            "This is an adult nutrition-support starting range, not measured energy expenditure.",
            "Confirm nutrition-support suitability, no severe illness/injury "
            "and no refeeding risk.",
            "Review activity, clinical condition, metabolic stability and all intake sources.",
            "Confirm current measured weight is appropriate (including fluid retention or loss).",
            "No automatic weight-loss deficit, activity multiplier or disease adjustment "
            "is applied.",
        ],
        "issues": [],
        "action": None,
        "calculation": None,
    }
    issues = result["issues"]
    for key in ("age_years", "weight_kg", "height_cm"):
        if facts.get(key) is None:
            issues.append(f"Record {key} to calculate the starting range.")
    if facts.get("age_years") is not None and facts["age_years"] < 18:
        issues.append("Children require a paediatric energy assessment.")
    for key in ("pregnant", "breastfeeding", "dialysis"):
        if facts.get(key) is True:
            issues.append(f"Individual energy assessment required: {key}.")
        elif facts.get(key) is None:
            result["review"].append(f"Clarify {key}; its status is unknown.")
    if issues:
        return result
    weight = Decimal(str(facts["weight_kg"]))
    height = Decimal(str(facts["height_cm"])) / 100
    bmi = weight / height**2
    result["bmi"] = float(bmi.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if bmi < Decimal("18.5"):
        result["review"].append(
            "BMI is below 18.5. The displayed range is an unadjusted reference, not a "
            "refeeding prescription; assess malnutrition and refeeding risk before using it."
        )
    elif bmi > 25:
        result["review"].append(
            "BMI is above 25. The displayed range uses recorded weight without adjustment; "
            "NICE notes that energy may need to be lower. Individualise before approval."
        )
    low, high = [
        float((weight * n).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for n in (25, 35)
    ]
    result["calculation"] = f"{weight} kg × 25–35 kcal/kg/day = {low:g}–{high:g} kcal/day"
    result["action"] = {
        "kind": "range",
        "subject": "energy",
        "amount": low,
        "upper": high,
        "unit": "kcal/day",
        "upper_exclusive": False,
        "advice": "Conditional NICE adult nutrition-support estimate; individualise after review.",
    }
    return result
