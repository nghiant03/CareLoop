"""Prepare/publish explicitly reviewed condition coverage from retained source snapshots.

Source acquisition snapshots and API audit output belong outside the repository.
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from careloop.evidence.diet_rules import ACTOR, excerpt
from careloop.evidence.models import RuleBody


def pred(fact, value, operator="eq"):
    return {"fact": fact, "operator": operator, "value": value}


def build_rules(sources):
    """Sources are keyed by reviewed document names; quotes must occur verbatim."""
    plan = []
    adult = [pred("age_years", 18, "gte")]
    ckd = [pred("has_ckd", True)]
    child_exceptions = [pred("age_years", 18, "gte")]

    def add(
        key,
        source,
        needle,
        subject,
        advice,
        applies,
        *,
        role="advisory",
        exceptions=(),
        action=None,
        location=None,
        note=None,
    ):
        document = sources[source]
        quote = excerpt(document, needle)
        body = RuleBody.model_validate(
            {
                "source_id": document["id"],
                "quote": quote,
                "location": location or quote.splitlines()[0],
                "applicability": applies,
                "exceptions": list(exceptions),
                "population_note": "Scope is defined by the structured predicates; source context "
                "and individual therapeutic suitability require review.",
                "exception_note": "No unrecorded clinical suitability is assumed. Review growth, "
                "nutrition status, comorbidities and treatment before adoption.",
                "review_role": role,
                "review_note": f"[condition-expansion:{key}] "
                + (
                    note
                    or (
                        "Source-backed counselling; not an executable nutrient bound."
                        if role == "advisory"
                        else "Individual assessment is required before setting a therapeutic "
                        "prescription."
                    )
                ),
                "action": {
                    "kind": "assessment",
                    "subject": subject,
                    "advice": advice,
                    **(action or {}),
                },
                "blockers": [],
            }
        ).model_dump(mode="json")
        plan.append({"key": key, "body": body})

    add(
        "ckd-diet-quality",
        "kdigo",
        "Practice Point 3.3.1: Advise people with CKD",
        "dietary_pattern",
        "Choose a healthy diverse diet with more plant-based than "
        "animal-based foods and fewer ultraprocessed foods, adapting choices to individual "
        "mineral requirements, allergies and growth needs.",
        ckd,
    )
    add(
        "ckd-individual-nutrients",
        "kdigo",
        "Practice Point 3.3.2: Use renal dietitians",
        "renal_nutrition",
        "Record renal dietitian/qualified nutrition review of sodium, "
        "phosphorus, potassium and protein needs in relation to CKD severity and comorbidities. "
        "Do not impose universal potassium or phosphorus restriction. Set numerical targets "
        "only where individually indicated.",
        ckd,
        role="required",
    )
    add(
        "ckd-child-growth",
        "kdigo",
        "Practice Point 3.3.1.4: Do not restrict protein",
        "growth_nutrition",
        "Do not restrict protein in children with CKD because of growth "
        "impairment risk. For CKD G2–G5, assess protein and energy toward the upper end of "
        "the normal healthy-child range. Record age/growth-specific targets with the renal "
        "team; adult 0.8 g/kg/day prescriptions must not be copied to children.",
        ckd,
        exceptions=child_exceptions,
        role="required",
    )
    add(
        "ckd-protein-suitability",
        "kdigo",
        "Practice Point 3.3.1.3: Do not prescribe",
        "protein_suitability",
        "Assess metabolic stability, malnutrition, sarcopenia and "
        "individual protein requirements before adopting CKD protein targets. Do not prescribe "
        "low/very-low-protein diets in metabolically unstable patients. Pregnancy, lactation "
        "and dialysis require separate prescriptions.",
        [*adult, *ckd],
        role="required",
    )
    for stage in ("G3a", "G3b", "G4", "G5"):
        add(
            f"ckd-protein-{stage}",
            "kdigo",
            "Recommendation 3.3.1.1: We suggest maintaining",
            "protein",
            "KDIGO suggests maintaining 0.8 g/kg/day in adults with CKD G3–G5. "
            "This is a reference intake, not a hard ceiling or an exact mandatory dose. "
            "Confirm appropriate body weight and suitability in the separate required protein "
            "assessment; adjust for malnutrition, frailty and metabolic instability.",
            [
                *adult,
                *ckd,
                pred("ckd_stage", stage),
                pred("dialysis", False),
                pred("pregnant", False),
                pred("breastfeeding", False),
            ],
            role="required",
            action={"kind": "intake", "amount": 0.8, "unit": "g/kg/day"},
            note="KDIGO 3.3.1.1 (2C), non-dialysis adult subset. Soft reference intake; "
            "the required suitability assessment governs individual adoption.",
        )

    for subject, needle, amount, unit in (
        ("fibre", "Everyone older than 10 years of age should also aim", 25, "g/day"),
        ("fruit_and_vegetables", "Everyone older than 10 years of age should aim", 400, "g/day"),
    ):
        add(
            f"adolescent-{subject}",
            "who",
            needle,
            subject,
            f"WHO reference minimum: {amount} {unit}. Review growth, therapeutic diet and "
            "renal restrictions before adoption; food contributions must be known.",
            [pred("age_years", 11, "gte")],
            exceptions=child_exceptions,
            role="required",
            action={"kind": "minimum", "amount": amount, "unit": unit},
            note="Conservative adolescent subset ages 11 to under 18 of the quoted "
            "older-than-10 recommendation, disjoint from existing adult rules.",
        )

    # HPB explicitly states that preceding recommendations apply to later categories.
    table = "<table><colgroup><col/><col/><col/><col/><col/><col/><col/><col/><col/></colgroup>"
    for condition, prefix in (
        ("Pre-Diabetes", "prediabetes"),
        ("Type 2 Diabetes Mellitus", "diabetes"),
        ("Type 2 Diabetes Mellitus at Risk of Hypoglycaemia", "hypoglycaemia"),
    ):
        applies = [pred("conditions", condition, "contains")]
        if prefix != "prediabetes":
            add(
                f"{prefix}-wholegrains",
                "hpb",
                table,
                "wholegrains",
                "Apply inherited HPB prediabetes guidance: substitute at least 50% of refined "
                "carbohydrates with wholegrains. This is a food substitution proportion, not "
                "a daily carbohydrate gram limit; adapt to treatment and renal needs.",
                applies,
            )
        add(
            f"{prefix}-meal-pairing",
            "hpb",
            table,
            "meal_composition",
            "Pair wholegrains with proteins and vegetables as recommended in the HPB "
            "prediabetes guidance (also inherited by diabetes/hypoglycaemia categories). "
            "Individualise portions; this does not imply an unrestricted protein intake.",
            applies,
        )
        if prefix == "prediabetes":
            add(
                "prediabetes-salt-sugar",
                "hpb",
                table,
                "dietary_pattern",
                "Apply the inherited baseline advice to reduce salt and sugar and increase "
                "soluble fibre. This passage supplies no additional numerical daily bound.",
                applies,
            )
        if prefix == "hypoglycaemia":
            add(
                "hypoglycaemia-alcohol",
                "hpb",
                table,
                "alcohol",
                "Review alcohol use and hypoglycaemia risk with the treating clinician; HPB "
                "advises caution with alcohol. Keep this separate from the existing required "
                "meal-regularity and carbohydrate-consistency assessment.",
                applies,
                role="required",
            )
    applies = [pred("conditions", "Hypertension", "contains")]
    add(
        "hypertension-dash",
        "hpb",
        table,
        "dietary_pattern",
        "Include DASH dietary components as recommended by HPB. Adapt the pattern for "
        "allergies and kidney disease; this is not an automatic potassium prescription.",
        applies,
    )
    add(
        "hypertension-lower-sodium-foods",
        "hpb",
        table,
        "food_choices",
        "Use lower-sodium alternatives, inherited from the HPB high-normal blood-pressure "
        "category. Review labels; do not assume potassium-based salt substitutes are suitable "
        "for people with CKD. The existing numeric sodium rule remains separate.",
        applies,
    )

    for fact, prefix in (("pregnant", "pregnancy"), ("breastfeeding", "lactation")):
        applies = [pred(fact, True)]
        add(
            f"{prefix}-calcium",
            "rda",
            '<h3 id="RDC">',
            "calcium",
            "The Singapore RDA table lists 1,000 mg/day calcium for pregnancy/breastfeeding. "
            "Review dietary intake and individual clinical needs. Calcium is not currently "
            "supported by the planner; this assessment does not claim meals meet that intake "
            "and is not an automatic supplement prescription.",
            applies,
            role="required",
        )
        if fact == "pregnant":
            add(
                "pregnancy-iron",
                "rda",
                "<th>Iron</th>",
                "iron",
                "The adult pregnancy RDA table lists 27 mg/day iron. Review diet and iron "
                "status with the clinician; the table footnote assumes 10–25% of dietary "
                "energy from animal foods. This is not a supplement dose or a planner-enforced "
                "target; individualise in anaemia and other clinical conditions.",
                [*adult, *applies],
                role="required",
            )
        else:
            add(
                "lactation-b12",
                "rda",
                "tbl32id2_0",
                "vitamin_b12",
                "The adult lactation table lists vitamin B12 2.8 micrograms/day. Review "
                "adequacy and dietary sources, particularly with restricted animal foods. "
                "This is not an automatic supplement prescription; B12 composition is not "
                "currently checked by the planner.",
                [*adult, *applies],
                role="required",
            )

    dialysis = [pred("dialysis", True)]
    add(
        "dialysis-protein",
        "nkf-protein",
        "On the other hand, once a person has started",
        "protein",
        "Dialysis changes protein needs: a higher protein intake is needed rather "
        "than carrying forward a non-dialysis low-protein diet. Have the kidney dietitian set "
        "the amount for body size, nutrition status and dialysis treatment; this source does "
        "not provide a universal numerical dose.",
        dialysis,
        role="required",
        location="On Dialysis: Increase Protein; Know the Right Amount of Protein for You",
    )
    add(
        "dialysis-potassium",
        "nkf-potassium",
        "If you have high potassium (hyperkalemia)",
        "potassium",
        "Review current potassium results and dialysis treatment with the renal "
        "team. High potassium may require limiting higher-potassium foods, whereas low "
        "potassium may require increasing intake. Record the individual decision rather "
        "than prescribing a universal low-potassium diet.",
        dialysis,
        role="required",
        location="About Potassium",
    )
    add(
        "dialysis-phosphorus",
        "nkf-phosphorus",
        "Yes. Dialysis can remove some phosphorus",
        "phosphorus",
        "Review phosphorus control between dialysis treatments with the renal "
        "team. Dialysis removes some phosphorus but dietary and treatment needs remain "
        "individual. Record an appropriate intake decision; no universal mg/day ceiling is "
        "supplied by this passage.",
        dialysis,
        role="required",
        location="Will dialysis help with phosphorus control?",
    )
    gout = [pred("conditions", "gout", "contains")]
    add(
        "gout-balanced-diet",
        "nice-gout",
        "Explain to people with gout that there is not enough",
        "dietary_pattern",
        "Follow a healthy balanced diet. Explain that evidence is "
        "insufficient to show that any specific diet prevents flares or lowers serum urate; "
        "dietary advice does not replace gout treatment.",
        gout,
        location="NG219 1.4.1",
    )
    add(
        "gout-weight",
        "nice-gout",
        "Advise people with gout that excess body weight",
        "weight_management",
        "Discuss excess body weight/obesity as a potential contributor "
        "to gout flares and symptoms, and individualise weight management where appropriate. "
        "Do not infer obesity or impose a calorie deficit from the gout diagnosis alone.",
        gout,
        location="NG219 1.4.2",
    )
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        type=Path,
        required=True,
        help="JSON mapping reviewed source names to full API source records",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = build_rules(json.loads(args.sources.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2))
    if not args.apply:
        print(f"Prepared {len(plan)} source-backed rules; no catalogue writes.")
        return

    def api(path, payload=None):
        request = urllib.request.Request(
            args.api.rstrip("/") + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    catalogue = api("/evidence/catalogue")
    (args.output / "catalogue-before-apply.json").write_text(json.dumps(catalogue, indent=2))
    resolved = []
    for entry in plan:
        body = entry["body"]
        # This publisher owns only explicitly keyed additions, never extraction drafts.
        marker = f"[condition-expansion:{entry['key']}]"
        matches = [r for r in catalogue["rules"] if marker in (r["draft"].get("review_note") or "")]
        if len(matches) > 1:
            raise RuntimeError(f"Ambiguous rule identity: {entry['key']}")
        row = matches[0] if matches else None
        if row and (
            row["retired"] or RuleBody.model_validate(row["draft"]).model_dump(mode="json") != body
        ):
            raise RuntimeError(f"Rule changed; review before updating: {entry['key']}")
        source = api("/evidence/sources/" + body["source_id"])
        if body["quote"] not in source["content"]:
            raise RuntimeError(f"Citation changed: {entry['key']}")
        resolved.append((entry, row))
    decision = {
        "actor": ACTOR,
        "reason": "User-requested condition coverage expansion; "
        "AI source review for academic demo, not independent clinician sign-off.",
    }
    refs = []
    for entry, row in resolved:
        if row and row["active_revision"] == row["latest_revision"]:
            continue
        row = row or api("/evidence/rules", {**decision, "body": entry["body"]})
        ref = {"rule_id": row["id"], "revision": row["latest_revision"]}
        refs.append(ref)
        with (args.output / "events.jsonl").open("a") as log:
            log.write(json.dumps({"key": entry["key"], **ref}) + "\n")
    if not refs:
        print("All condition-expansion rules are already active.")
        return
    batch = {**decision, "rules": refs}
    api("/evidence/approvals", batch)
    report = api("/evidence/conflict-check", batch)
    (args.output / "conflicts.json").write_text(json.dumps(report, indent=2))
    if report["blocking_conflicts"]:
        raise RuntimeError("Blocking conflicts; reviewed drafts retained, not published")
    # Only the explicitly reviewed overlap subjects are allowed in this publication.
    allowed = {
        "protein",
        "dietary_pattern",
        "food_choices",
        "wholegrains",
        "meal_composition",
        "calcium",
        "iron",
        "vitamin_b12",
        "potassium",
        "phosphorus",
        "alcohol",
        "weight_management",
        "fibre",
        "fruit_and_vegetables",
        "renal_nutrition",
        "growth_nutrition",
        "protein_suitability",
    }
    if any(f["subject"] not in allowed for f in report["review_findings"]):
        raise RuntimeError("Unexpected overlap; review the saved conflict report")
    publication = api(
        "/evidence/publications",
        {
            **batch,
            "expected_generation": report["generation"],
            "conflict_review": "Adult non-dialysis CKD protein is a soft 0.8 g/kg reference, "
            "not a ceiling; separate suitability assessment requires clinical review. Stage "
            "variants are disjoint; children, dialysis, pregnancy and lactation are excluded "
            "from this adult reference. Paediatric CKD requires growth-appropriate energy/protein "
            "rather than restriction. Adolescent WHO minima are disjoint from adult/child bands "
            "and require review against renal needs. HPB food-quality guidance is complementary "
            "to portion/timing assessments, never a numerical carbohydrate restriction. Calcium "
            "and B12 pregnancy/lactation overlaps are reference reviews, not additive doses. "
            "Dialysis mineral and protein rules require individual prescriptions; they do not "
            "remove the existing dialysis planning scope blocker. Gout balanced diet/weight "
            "counselling complements alcohol advice and does not claim urate-lowering efficacy. "
            "No patient approval or diagnosis is made by this publication.",
        },
    )
    (args.output / "publication.json").write_text(json.dumps(publication, indent=2))
    after = api("/evidence/catalogue")
    (args.output / "catalogue-after.json").write_text(json.dumps(after, indent=2))
    lookup = {r["id"]: r for r in after["rules"]}
    for ref in refs:
        if lookup[ref["rule_id"]]["active_revision"] != ref["revision"]:
            raise RuntimeError("Published revision read-back mismatch")
    print(f"Published and verified {len(refs)} condition-coverage rules.")


if __name__ == "__main__":
    main()
