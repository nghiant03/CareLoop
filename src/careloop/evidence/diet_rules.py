"""Reviewed source-backed numeric rules; apply explicitly after deploying the planner.

Run `python -m careloop.evidence.diet_rules --help`. No patient targets are approved.
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from careloop.evidence.models import RuleBody

WHO = "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"
KDIGO = "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf"
ACTOR = {"name": "OpenCode AI source review (user-authorized academic demo)", "role": "reviewer"}
REASON = (
    "User-requested conversion to executable, source-backed nutrition rules. "
    "Reviewed WHO healthy diet and KDIGO 2024. Adult age >=18 is an explicitly "
    "reviewer-selected subset. Not independent clinician sign-off. "
    "All patient targets still require clinician selection and approval."
)
REVIEW = (
    "Reviewed general and condition-specific overlap: WHO and CKD sodium limits agree "
    "at <2000 mg/day. The hypertension <=2000 mg rule differs at equality; clinicians "
    "must explicitly select the appropriate target rather than silently merging them. "
    "Sodium-wasting nephropathy is an exception; its existing assessment takes precedence. "
    "Energy-dependent sugar/fat limits use actual energy and do not prescribe 2000 kcal. "
    "Children's fibre age bands are disjoint from the adult baseline. Saturated fat and "
    "trans fat are separate nutrients, not additive percentages of the same nutrient. "
    "Food-group targets require documented qualifying edible grams. Other therapeutic "
    "needs, malnutrition and suitability must be reviewed at patient-target approval."
)


def excerpt(source, start):
    """Use a whole retained paragraph, including its original heading."""
    matches = [p for p in source["content"].split("\n\n") if start in p]
    if not matches:
        raise ValueError(f"Source passage missing: {start}")
    return min(matches, key=len)


def build_rules(who, kdigo):
    exception_quote = excerpt(kdigo, "Dietary sodium restriction is usually not appropriate")
    if "sodium-wasting nephropathy" not in exception_quote:
        raise ValueError("Review the KDIGO sodium exception before applying rules")
    adult = [{"fact": "age_years", "operator": "gte", "value": 18}]
    definitions = [
        (
            "adult-fruit-vegetables",
            who,
            "Everyone older than 10 years of age should aim",
            "minimum",
            "fruit_and_vegetables",
            400,
            "g/day",
            False,
            adult,
            "Aim for at least 400 g/day of qualifying fruit and vegetables. Count documented "
            "edible contributions only; review recipe composition and dietary suitability.",
        ),
        (
            "adult-fibre",
            who,
            "Everyone older than 10 years of age should also aim",
            "minimum",
            "fibre",
            25,
            "g/day",
            False,
            adult,
            "Aim for at least 25 g/day of naturally occurring dietary fibre from foods. "
            "Review therapeutic dietary needs before approving this minimum.",
        ),
        (
            "adult-free-sugars",
            who,
            "The consumption of free sugars should be limited",
            "ceiling",
            "free_sugars",
            10,
            "%energy",
            True,
            adult,
            "Keep free sugars below 10% of actual daily energy. Do not substitute total or "
            "added sugars for free sugars. No universal 50 g/day allowance is assumed.",
        ),
        (
            "adult-saturated-fat",
            who,
            "No more than 10% of total energy intake",
            "ceiling",
            "saturated_fat",
            10,
            "%energy",
            False,
            adult,
            "Limit saturated fat to no more than 10% of actual daily energy; replace it "
            "with suitable unsaturated fats or naturally fibre-containing carbohydrate foods.",
        ),
        (
            "adult-trans-fat",
            who,
            "No more than 10% of total energy intake",
            "ceiling",
            "trans_fat",
            1,
            "%energy",
            False,
            adult,
            "Limit trans fat to no more than 1% of actual daily energy. WHO also advises "
            "avoiding industrially produced trans fat; this numerical limit alone does not "
            "certify its absence.",
        ),
        (
            "adult-sodium",
            who,
            "In adults, salt intake should be limited",
            "ceiling",
            "sodium",
            2000,
            "mg/day",
            True,
            adult,
            "Keep sodium below 2,000 mg/day (WHO: less than 5 g salt/day). Review therapeutic "
            "exceptions. Potassium-containing salt substitutes are not automatically recommended.",
        ),
        (
            "child-fibre-2-5",
            who,
            "Everyone older than 10 years of age should also aim",
            "minimum",
            "fibre",
            15,
            "g/day",
            False,
            [
                {"fact": "age_years", "operator": "gte", "value": 2},
                {"fact": "age_years", "operator": "lte", "value": 5},
            ],
            "For children aged 2–5, aim for at least 15 g/day naturally occurring dietary fibre.",
        ),
        (
            "child-fibre-6-9",
            who,
            "Everyone older than 10 years of age should also aim",
            "minimum",
            "fibre",
            21,
            "g/day",
            False,
            [
                {"fact": "age_years", "operator": "gte", "value": 6},
                {"fact": "age_years", "operator": "lte", "value": 9},
            ],
            "For children aged 6–9, aim for at least 21 g/day naturally occurring dietary fibre.",
        ),
        (
            "ckd-adult-sodium",
            kdigo,
            "Recommendation 3.3.2.1: We suggest that sodium intake",
            "ceiling",
            "sodium",
            2000,
            "mg/day",
            True,
            [*adult, {"fact": "has_ckd", "operator": "eq", "value": True}],
            "KDIGO suggests sodium below 2 g/day (2,000 mg/day) in CKD (2C). This adult "
            "subset requires review of sodium-wasting nephropathy, malnutrition and unusual "
            "sodium losses, including extreme heat, before approval.",
        ),
    ]
    result = []
    required_support = {
        "adult-fruit-vegetables": ["at least 400 grams"],
        "adult-fibre": ["at least 25 grams"],
        "adult-free-sugars": ["less than 10% of total daily energy intake"],
        "adult-saturated-fat": ["No more than 10% of total energy intake"],
        "adult-trans-fat": ["no more than 1% of total energy from trans fat"],
        "adult-sodium": ["less than 5 grams per day (2 grams per day sodium)"],
        "child-fibre-2-5": ["at least 15 or 21 grams", "2–5 or 6–9 years of age"],
        "child-fibre-6-9": ["at least 15 or 21 grams", "2–5 or 6–9 years of age"],
        "ckd-adult-sodium": ["sodium intake be <2 g of sodium per day"],
    }
    for (
        key,
        source,
        start,
        kind,
        subject,
        amount,
        unit,
        strict,
        applicability,
        advice,
    ) in definitions:
        quote = excerpt(source, start)
        if not all(text in quote for text in required_support[key]):
            raise ValueError(f"Source recommendation changed; review {key} before applying")
        sodium = subject == "sodium"
        body = RuleBody.model_validate(
            {
                "source_id": source["id"],
                "quote": quote,
                "location": (
                    "KDIGO 2024, Recommendation 3.3.2.1; retained section 3.3.2 Sodium intake"
                    if source is kdigo
                    else quote.split("\n", 1)[0]
                ),
                "applicability": applicability,
                "population_note": (
                    "Reviewer-selected adult subset (age >=18); baseline proposals are not "
                    "a substitute for individual therapeutic assessment."
                    if applicability[0]["value"] == 18
                    else "Children in the explicitly specified WHO age band."
                )
                + (" Documented CKD required." if key.startswith("ckd") else ""),
                "exceptions": (
                    [
                        {
                            "fact": "conditions",
                            "operator": "contains",
                            "value": "sodium-wasting nephropathy",
                        }
                    ]
                    if sodium
                    else []
                ),
                "exception_note": (
                    "Cross-source reviewer qualification: KDIGO 2024 Practice Point 3.3.2.1 "
                    "says sodium restriction is usually inappropriate in sodium-wasting "
                    "nephropathy. Also review malnutrition, unusual losses and individual clinical "
                    "needs; the structured exception vocabulary is not an exhaustive history."
                    if sodium
                    else "Review allergies, life stage, tolerance and therapeutic restrictions "
                    "before approving a patient target; no general-population rule overrides "
                    "that assessment."
                ),
                "action": {
                    "kind": kind,
                    "subject": subject,
                    "amount": amount,
                    "unit": unit,
                    "upper_exclusive": strict,
                    "advice": advice,
                },
                "blockers": [],
            }
        ).model_dump(mode="json")
        result.append({"key": key, "body": body})
    return result


def resolve_matches(plan, rules):
    resolved = []
    for entry in plan:
        body = entry["body"]
        matching = [
            r
            for r in rules
            if not r["retired"]
            and r["draft"]["source_id"] == body["source_id"]
            and r["draft"]["action"]["subject"] == body["action"]["subject"]
            and r["draft"]["applicability"] == body["applicability"]
        ]
        # Published identity takes precedence over separate extraction drafts.
        published = [r for r in matching if r["active_revision"] is not None]
        candidates = published or matching
        if len(candidates) > 1:
            raise RuntimeError(
                f"Ambiguous existing rules for {entry['key']}; review before applying"
            )
        resolved.append((entry, candidates[0] if candidates else None))
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--output", type=Path, required=True, help="Audit directory outside Git")
    parser.add_argument(
        "--apply", action="store_true", help="Create/revise, approve and publish reviewed rules"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def api(path, payload=None):
        req = urllib.request.Request(
            args.api.rstrip("/") + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    sources = []
    while True:
        page = api(f"/evidence/sources?limit=100&offset={len(sources)}")
        sources.extend(page)
        if len(page) < 100:
            break
    selected = []
    for url in (WHO, KDIGO):
        matching = [s for s in sources if s["locator"] == url]
        if not matching:
            raise ValueError(f"Acquire the authoritative source first: {url}")
        selected.append(api("/evidence/sources/" + matching[-1]["id"]))
    plan = build_rules(*selected)
    (args.output / "sources.json").write_text(json.dumps(selected, indent=2))
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2))
    if not args.apply:
        print(f"Prepared {len(plan)} source-backed rules; no writes. Use --apply after deployment.")
        return
    # Reject an old server before creating unsupported targets or partially publishing.
    with urllib.request.urlopen(
        args.api.rstrip("/").removesuffix("/api") + "/openapi.json", timeout=30
    ) as response:
        schema = json.load(response)["components"]["schemas"]["Action"]["properties"]
    if "minimum" not in schema["kind"]["enum"] or "upper_exclusive" not in schema:
        raise RuntimeError("Deploy the updated API before applying executable nutrition rules")
    catalogue = api("/evidence/catalogue")
    (args.output / "catalogue-before.json").write_text(json.dumps(catalogue, indent=2))
    decision = {"actor": ACTOR, "reason": REASON}
    refs = []
    for entry, row in resolve_matches(plan, catalogue["rules"]):
        body = entry["body"]
        if row and RuleBody.model_validate(row["draft"]).model_dump(mode="json") == body:
            if row["active_revision"] == row["latest_revision"]:
                continue
        elif row:
            row = api(
                f"/evidence/rules/{row['id']}/revisions",
                {**decision, "expected_revision": row["latest_revision"], "body": body},
            )
        else:
            row = api("/evidence/rules", {**decision, "body": body})
        ref = {"rule_id": row["id"], "revision": row["latest_revision"]}
        refs.append(ref)
        with (args.output / "events.jsonl").open("a") as log:
            log.write(json.dumps({"key": entry["key"], **ref}) + "\n")
    if not refs:
        print("All reviewed numeric rules are already active.")
        return
    batch = {**decision, "rules": refs}
    api("/evidence/approvals", batch)
    conflicts = api("/evidence/conflict-check", batch)
    (args.output / "conflicts.json").write_text(json.dumps(conflicts, indent=2))
    allowed = {
        "sodium",
        "fibre",
        "free_sugars",
        "saturated_fat",
        "trans_fat",
        "fruit_and_vegetables",
    }
    if conflicts["blocking_conflicts"] or any(
        f["subject"] not in allowed for f in conflicts["review_findings"]
    ):
        raise RuntimeError("Review unexpected conflicts before publication; drafts retained")
    publication = api(
        "/evidence/publications",
        {**batch, "expected_generation": conflicts["generation"], "conflict_review": REVIEW},
    )
    (args.output / "publication.json").write_text(json.dumps(publication, indent=2))
    after = api("/evidence/catalogue")
    lookup = {r["id"]: r for r in after["rules"]}
    assert all(lookup[r["rule_id"]]["active_revision"] == r["revision"] for r in refs)
    (args.output / "catalogue-after.json").write_text(json.dumps(after, indent=2))
    print(
        f"Published and read-back verified {len(refs)} numeric rules. "
        "Patient approval remains separate."
    )


if __name__ == "__main__":
    main()
