"""Model-blinded review packets and validated, separately stored assessment results."""

from pathlib import Path

from careloop.evaluation.storage import digest, read, write


def export_packets(directory):
    """Expose source, frozen reference, and answer, but not model identity or automatic score."""
    directory = Path(directory)
    groups = {"extraction": [], "chat": []}
    mapping = {}
    selection = read(directory / "manifest.json").get("semantic_review", {}).get("cases")
    for path in sorted((directory / "requests").glob("*.json")):
        row = read(path)
        if row["state"] != "completed":
            continue
        task = row["task"]
        if selection and task["case_id"] not in selection[task["split"]][task["task"]]:
            continue
        identity = digest({"blind_review": row["id"]})[:20]
        mapping[identity] = row["id"]
        groups[task["task"]].append(
            {
                "review_id": identity,
                "split": task["split"],
                "condition": task["condition"],
                "source": task.get("passage", task.get("sources")),
                "reference": task["reference"],
                "output": row["result"],
            }
        )
    for task, rows in groups.items():
        rows.sort(key=lambda row: row["review_id"])
        write(directory / f"blind-{task}.json", rows)
    write(directory / "blind-mapping.json", mapping)
    return {task: len(rows) for task, rows in groups.items()}


def import_assessments(directory, files):
    """Review labels are external inputs, never inferred from model agreement."""
    directory = Path(directory)
    mapping = read(directory / "blind-mapping.json")
    labels = []
    seen = set()
    for file in files:
        for label in read(file):
            identity = label["review_id"]
            if identity not in mapping or identity in seen:
                raise ValueError("Unknown or duplicate review identity")
            seen.add(identity)
            required = ("correct", "supported", "relevant")
            if any(not isinstance(label.get(key), bool) for key in required):
                raise ValueError("Assessments require boolean correct/supported/relevant labels")
            if not label.get("rationale"):
                raise ValueError("Assessments require a source-linked rationale")
            labels.append({**label, "request_id": mapping[identity]})
    result = {
        "state": "complete" if len(seen) == len(mapping) else "partial",
        "method": "Model-blinded team assessment against frozen source references",
        "reviewed": len(seen),
        "eligible": len(mapping),
        "labels": labels,
        "limitation": "Reference-based team assessment, not clinician validation.",
    }
    write(directory / "semantic-review.json", result)
    return result
