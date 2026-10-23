"""Import supporting software-check results without treating skips as successes."""

from pathlib import Path
from xml.etree import ElementTree

from careloop.evaluation.storage import write

WORKFLOW_FILES = {
    "test_evidence",
    "test_extraction",
    "test_patients",
    "test_planning",
    "test_recommendations",
    "test_logging",
    "test_meal_items",
    "test_chat",
    "test_evaluation_workflow",
}


def import_junit(directory, path, *, command, runtime):
    tree = ElementTree.parse(path)
    cases = []
    for item in tree.iter("testcase"):
        state = "passed"
        for tag, value in (("skipped", "skipped"), ("failure", "failed"), ("error", "error")):
            if item.find(tag) is not None:
                state = value
        cases.append(
            {
                "class": item.get("classname"),
                "name": item.get("name"),
                "seconds": float(item.get("time", 0)),
                "state": state,
                "workflow_related": item.get("classname", "").split(".")[-1] in WORKFLOW_FILES,
            }
        )
    result = {
        "command": command,
        "runtime": runtime,
        "cases": cases,
        "counts": {
            state: sum(c["state"] == state for c in cases)
            for state in ("passed", "failed", "error", "skipped")
        },
        "scope": "Supporting software verification; fixtures are not clinical cohorts",
    }
    write(Path(directory) / "verification.json", result)
    return result
