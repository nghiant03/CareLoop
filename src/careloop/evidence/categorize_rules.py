"""Apply an explicitly reviewed classification manifest without changing clinical actions."""

import argparse
import json
import urllib.request
from pathlib import Path

from careloop.evidence.models import RuleBody

ACTOR = {"name": "OpenCode AI source review (user-authorized academic demo)", "role": "reviewer"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    review = json.loads(args.review.read_text())
    planned = []
    seen = set()
    for entry in review:
        if entry["rule_id"] in seen:
            raise ValueError("Duplicate rule in review manifest")
        seen.add(entry["rule_id"])
        before = RuleBody.model_validate(entry["before"]).model_dump(mode="json")
        body = RuleBody.model_validate(entry["body"]).model_dump(mode="json")
        changed = {key for key in body if body[key] != before[key]}
        if not changed <= {"review_role", "review_note"}:
            raise ValueError("Classification review cannot change actions, scope or citations")
        if changed:
            planned.append((entry, body))
    if not args.apply:
        print(
            f"Reviewed {len(review)} active rules; {len(planned)} classification revisions ready."
        )
        return

    def api(path, payload=None):
        request = urllib.request.Request(
            args.api.rstrip("/") + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    with urllib.request.urlopen(args.api.rstrip("/").removesuffix("/api") + "/openapi.json") as r:
        schemas = json.load(r)["components"]["schemas"]
    if "review_role" not in schemas["RuleBody"]["properties"]:
        raise RuntimeError("Rebuild the API before applying rule categories; no rules written")
    catalogue = api("/evidence/catalogue")
    lookup = {r["id"]: r for r in catalogue["rules"]}
    resolved = []
    for entry, body in planned:
        row = lookup.get(entry["rule_id"])
        if row is None or row["retired"] or row["active_revision"] is None:
            raise RuntimeError(f"Published rule unavailable: {entry['rule_id']}")
        draft = RuleBody.model_validate(row["draft"]).model_dump(mode="json")
        before = RuleBody.model_validate(entry["before"]).model_dump(mode="json")
        if draft != body and (row["latest_revision"] != entry["revision"] or draft != before):
            raise RuntimeError(f"Rule changed since review: {entry['rule_id']}")
        resolved.append((row, body, entry["reason"]))
    refs = []
    for row, body, reason in resolved:
        draft = RuleBody.model_validate(row["draft"]).model_dump(mode="json")
        if draft == body and row["active_revision"] == row["latest_revision"]:
            continue
        if draft != body:
            row = api(
                f"/evidence/rules/{row['id']}/revisions",
                {
                    "actor": ACTOR,
                    "reason": reason,
                    "expected_revision": row["latest_revision"],
                    "body": body,
                },
            )
        refs.append({"rule_id": row["id"], "revision": row["latest_revision"]})
    if not refs:
        print("Reviewed rule classifications are already active.")
        return
    batch = {
        "actor": ACTOR,
        "reason": "Publish user-requested source-reviewed rule categories",
        "rules": refs,
    }
    api("/evidence/approvals", batch)
    conflicts = api("/evidence/conflict-check", batch)
    args.review.with_name("category-conflicts.json").write_text(json.dumps(conflicts, indent=2))
    if conflicts["blocking_conflicts"]:
        raise RuntimeError("Blocking conflicts require review; classification drafts retained")
    publication = api(
        "/evidence/publications",
        {
            **batch,
            "expected_generation": conflicts["generation"],
            "conflict_review": (
                "Classification-only source review. Actions, populations, exceptions and quotes "
                "are unchanged. Numeric sodium limits and clinical assessment requirements retain "
                "their prior interpretation. Advisory food-quality/gout-prevention advice does "
                "not replace condition-specific assessments or numerical limits. Required energy, "
                "diabetes/hypoglycaemia, pregnancy/lactation, sodium-wasting and CKD assessments "
                "remain mandatory. AI review under user authorization; "
                "not clinician target approval."
            ),
        },
    )
    args.review.with_name("category-publication.json").write_text(json.dumps(publication, indent=2))
    after = api("/evidence/catalogue")
    lookup = {r["id"]: r for r in after["rules"]}
    for entry, body in planned:
        assert (
            RuleBody.model_validate(lookup[entry["rule_id"]]["published"]).model_dump(mode="json")
            == body
        )
    args.review.with_name("catalogue-after.json").write_text(json.dumps(after, indent=2))
    print(f"Published and verified {len(refs)} classification revisions.")


if __name__ == "__main__":
    main()
