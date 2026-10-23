"""Prepare frozen inputs, execute bounded experiments, and report saved outcomes."""

import hashlib
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

from careloop.evaluate_foods import evaluate_export
from careloop.evaluation import language, planning, substitutions
from careloop.evaluation.storage import (
    DEFAULT_ROOT,
    code_hashes,
    digest,
    environment,
    freeze,
    now,
    read,
    write,
)
from careloop.inference import InferenceClient, Settings

REFERENCE_DIR = Path(__file__).parent
REFERENCE_FILES = (
    "references.json",
    "references_singapore.json",
    "references_clinical.json",
    "references_who.json",
)


def load_references(paths):
    """Load existing labelled files without creating or altering reference annotations."""
    sets = [read(path) for path in paths]
    return {
        "schema_version": "careloop-reference-bundle-v1",
        "reference_sets": [
            {
                "file": Path(path).name,
                "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "provenance": corpus.get("provenance"),
                "limitations": corpus.get("limitations", []),
            }
            for path, corpus in zip(paths, sets, strict=True)
        ],
        "documents": [doc for corpus in sets for doc in corpus["documents"]],
        "passages": [passage for corpus in sets for passage in corpus["passages"]],
        "questions": [question for corpus in sets for question in corpus["questions"]],
    }


def validate_references(corpus):
    documents = corpus["documents"]
    ids = [doc["id"] for doc in documents]
    if len(ids) != len(set(ids)) or not {"dev", "test"} <= {d["split"] for d in documents}:
        raise ValueError("Unique documents and both dev/test splits are required")
    locations = [doc["official_url"] for doc in documents]
    if len(set(locations)) != len(locations):
        raise ValueError("Related snapshots of the same source must remain in one document group")
    passages = {p["id"]: p for p in corpus["passages"]}
    if len(passages) != len(corpus["passages"]):
        raise ValueError("Duplicate passage IDs")
    splits = {doc["id"]: doc["split"] for doc in documents}
    contents = set()
    for passage in passages.values():
        if passage["document_id"] not in ids or not passage["content"].strip():
            raise ValueError("Every passage requires a known document and nonempty source text")
        if passage.get("split", splits[passage["document_id"]]) != splits[passage["document_id"]]:
            raise ValueError("Passage split differs from its source document")
        normalized = " ".join(passage["content"].split())
        if normalized in contents:
            raise ValueError("Duplicate passage content inflates the benchmark")
        contents.add(normalized)
        if len(passage["reference_extraction"]["rules"]) > 3:
            raise ValueError("Reference exceeds the application's three-rule passage limit")
    seen = set()
    for question in corpus["questions"]:
        if question["id"] in seen:
            raise ValueError("Duplicate question IDs")
        seen.add(question["id"])
        for identity in question["passage_ids"]:
            if splits[passages[identity]["document_id"]] != question["split"]:
                raise ValueError("Question context crosses document split")


def prepare(
    root=DEFAULT_ROOT, *, references=None, planning_references=None, food_export=None, models=None
):
    """Load static team-labelled references; no reference authoring or LLM calls."""
    root = Path(root).expanduser()
    paths = [Path(references)] if references else [REFERENCE_DIR / name for name in REFERENCE_FILES]
    corpus = load_references(paths)
    validate_references(corpus)
    cases = read(planning_references or REFERENCE_DIR / "planning_references.json")
    selected_models = list(models or language.MODELS)
    if len(selected_models) != 4 or len(set(selected_models)) != 4:
        raise ValueError("The frozen comparison requires four distinct catalogue model IDs")
    food = None
    if food_export:
        path = Path(food_export).expanduser().resolve()
        food = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        "schema_version": 1,
        "references": corpus,
        "planning_references": cases,
        "models": selected_models,
        "generation": language.OPTIONS.model_dump(mode="json"),
        "food_export": food,
        "retrieval": {"limit": 1000, "clusters": 4, "top": 5},
        "planning": {"random_seeds": [17, 43, 91], "random_budget": 2000, "exact_limit": 100000},
        "scoring_version": "careloop-system-evaluation-v1",
        "code_sha256": code_hashes(),
        "reference_policy": "Static team-labelled references, frozen before inference",
        "split_policy": "Document-group holdout; no final-test prompt tuning",
        "semantic_review": {
            "selection": "Lowest SHA256(case ID), separately within task and split; "
            "4 extraction and 6 answer cases per split, all models and selected ablations",
            "cases": {
                split: {
                    "extraction": [
                        p["id"]
                        for p in sorted(
                            [p for p in corpus["passages"] if p["split"] == split],
                            key=lambda p: digest(p["id"]),
                        )[:4]
                    ],
                    "chat": [
                        q["id"]
                        for q in sorted(
                            [q for q in corpus["questions"] if q["split"] == split],
                            key=lambda q: digest(q["id"]),
                        )[:6]
                    ],
                }
                for split in ("dev", "test")
            },
        },
    }
    identity = digest(manifest)
    directory = root / identity
    freeze(directory / "manifest.json", manifest)
    return directory


def run_local(directory):
    directory = Path(directory)
    manifest = read(directory / "manifest.json")
    path = directory / "local.json"
    if path.exists():
        return read(path)
    spec = manifest["planning_references"]
    result = {
        "started_at": now(),
        "environment": environment(),
        "planning": [],
        "substitutions": [],
    }
    for case in spec.get("usable_planning_cases", []):
        measured = planning.benchmark(case, **manifest["planning"])
        result["planning"].append(measured)
        alternatives = [
            a
            for method in measured.get("methods", [])
            if method["method"] == "beam"
            for a in method["alternatives"]
            if a["independent_audit"]["valid"]
        ]
        if alternatives:
            result["substitutions"].append(substitutions.benchmark(case, alternatives[0]["meals"]))
    if not result["planning"]:
        result["planning_status"] = "blocked"
        result["planning_blockers"] = spec.get("blockers", [])
        result["checked_substitution_status"] = "blocked"
    else:
        result["planning_status"] = "executed"
        result["checked_substitution_status"] = "executed" if result["substitutions"] else "blocked"
    food = manifest["food_export"]
    if food:
        source = Path(food["path"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != food["sha256"]:
            raise ValueError("Food export changed after freezing")
        result["retrieval"] = evaluate_export(source, **manifest["retrieval"])
    else:
        result["retrieval"] = {"state": "skipped", "reason": "No frozen food export supplied"}
    result["finished_at"] = now()
    write(path, result)
    return result


def run(directory, *, splits=("dev", "test"), workers=4, hosted=True):
    """Resume saved calls; failed/pending calls remain failures/unknown, never auto-retried."""
    directory = Path(directory)
    manifest = read(directory / "manifest.json")
    if manifest["code_sha256"] != code_hashes():
        raise ValueError("Implementation changed after freeze; prepare a new experiment")
    run_local(directory)
    if hosted:
        with InferenceClient(Settings.load()) as client:
            catalogue = client.models()
            endpoint_hash = hashlib.sha256(client.settings.base_url.encode()).hexdigest()
        missing = set(manifest["models"]) - set(catalogue)
        if missing:
            raise ValueError(f"Frozen models missing from catalogue: {sorted(missing)}")
        freeze(
            directory / "catalogue.json", {"models": catalogue, "endpoint_sha256": endpoint_hash}
        )
        for split in splits:
            if split not in {"dev", "test"}:
                raise ValueError("Use dev or test split")
            tasks = language.tasks(manifest["references"], split, manifest["models"])
            outcomes = language.run_tasks(tasks, directory, endpoint_hash, workers)
            write(directory / f"{split}-index.json", [outcome["id"] for outcome in outcomes])
    return report(directory)


def run_pilot(directory, *, workers=4):
    return run(directory, splits=("dev",), workers=workers)


def reuse_language_cache(source, destination):
    """Reuse identical requests only when the inference/prompts/scorer code is unchanged."""
    source, destination = Path(source), Path(destination)
    before = read(source / "manifest.json")
    after = read(destination / "manifest.json")
    current_endpoint = hashlib.sha256(Settings.load().base_url.encode()).hexdigest()
    if read(source / "catalogue.json")["endpoint_sha256"] != current_endpoint:
        raise ValueError("Cannot reuse calls from a different inference endpoint")
    relevant = ("inference.py", "answers.py", "evidence/extraction.py", "evaluation/language.py")
    if any(before["code_sha256"][key] != after["code_sha256"][key] for key in relevant):
        raise ValueError("Cannot reuse calls after inference, prompt, or language-scoring changes")
    expected = {
        digest(task)
        for split in ("dev", "test")
        for task in language.tasks(after["references"], split, after["models"])
    }
    reused = []
    for path in sorted((source / "requests").glob("*.json")):
        row = read(path)
        if digest(row["task"]) not in expected:
            continue
        target = destination / "requests" / path.name
        if target.exists():
            if read(target) != row:
                raise ValueError("Existing destination request differs from cached outcome")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        reused.append(row["id"])
    if reused:
        provenance_path = destination / "cache-reuse.json"
        previous = read(provenance_path) if provenance_path.exists() else {"sources": []}
        previous["sources"].append({"source_experiment": source.name, "request_ids": reused})
        write(provenance_path, previous)
    return len(reused)


def report(directory, *, destination=None):
    """Offline report from saved outputs; credentials and provider calls are unnecessary."""
    directory = Path(directory)
    manifest = read(directory / "manifest.json")
    records = [read(path) for path in sorted((directory / "requests").glob("*.json"))]
    grouped = defaultdict(list)
    for row in records:
        task = row["task"]
        grouped[(task["split"], task["task"], task["condition"], task["model"])].append(row)
    summaries = []
    for key, rows in sorted(grouped.items()):
        complete = [r for r in rows if r["state"] == "completed"]
        latencies = [r["seconds"] for r in rows if "seconds" in r]
        summaries.append(
            {
                "split": key[0],
                "task": key[1],
                "condition": key[2],
                "model": key[3],
                "attempted": len(rows),
                "completed": len(complete),
                "failed": sum(r["state"] == "failed" for r in rows),
                "pending_unknown": sum(r["state"] == "pending" for r in rows),
                "bounded_pass": sum(r.get("scores", {}).get("bounded_pass", False) for r in rows),
                "median_seconds": statistics.median(latencies) if latencies else None,
                "total_tokens": sum(
                    r.get("response", {}).get("usage", {}).get("total_tokens", 0) or 0 for r in rows
                ),
                "matched_actions": sum(r["scores"].get("matched_actions", 0) for r in complete),
                "returned_actions": sum(r["scores"].get("returned_actions", 0) for r in complete),
                "reference_actions_completed": sum(
                    r["scores"].get("reference_actions", 0) for r in complete
                ),
            }
        )
    local = read(directory / "local.json") if (directory / "local.json").exists() else {}
    review_path = directory / "semantic-review.json"
    review = read(review_path) if review_path.exists() else {"state": "not_performed"}
    lookup = {row["id"]: row for row in records}
    semantic = defaultdict(list)
    for label in review.get("labels", []):
        task = lookup[label["request_id"]]["task"]
        semantic[(task["split"], task["task"], task["condition"], task["model"])].append(label)
    semantic_summary = [
        {
            "split": key[0],
            "task": key[1],
            "condition": key[2],
            "model": key[3],
            "reviewed": len(labels),
            **{
                field: sum(label[field] for label in labels)
                for field in ("correct", "supported", "relevant")
            },
        }
        for key, labels in sorted(semantic.items())
    ]
    expected = {
        split: len(language.tasks(manifest["references"], split, manifest["models"]))
        for split in ("dev", "test")
    }
    result = {
        "schema_version": 1,
        "experiment_id": directory.name,
        "manifest_sha256": digest(manifest),
        "expected_calls": expected,
        "saved_calls": len(records),
        "language": summaries,
        "local": local,
        "semantic_review": review,
        "semantic_summary": semantic_summary,
        "limitations": [
            "Bounded automatic scores do not establish semantic claim support.",
            "Guideline answering uses the production cited-answer component with supplied passages;"
            "it does not measure live retrieval or persisted patient-chat quality.",
            "Evidence-removal ablation measures grounding/abstention, not unrestricted medical QA.",
            "No clinician validation, human usability study or outcome study.",
            "Real-source planning prerequisites may block experiments; blocked is not passing.",
            "Hosted outputs can vary; cached report reproduction does not imply identical "
            "fresh calls.",
        ],
    }
    verification_path = directory / "verification.json"
    if verification_path.exists():
        result["verification"] = read(verification_path)
    target = Path(destination) if destination else directory
    write(target / "summary.json", result)
    lines = [
        "# CareLoop system evaluation",
        "",
        f"Experiment: `{directory.name}`",
        "",
        "## Language experiments",
        "",
        "Bounded checks are source-linked field/pattern checks, not semantic accuracy.",
        "",
        "| Split | Task | Context | Model | Completed / attempted | "
        "Bounded pass / attempted | Median s |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in summaries:
        latency = f"{row['median_seconds']:.2f}" if row["median_seconds"] is not None else "—"
        lines.append(
            f"| {row['split']} | {row['task']} | {row['condition']} | {row['model']} | "
            f"{row['completed']}/{row['attempted']} | "
            f"{row['bounded_pass']}/{row['attempted']} | {latency} |"
        )
    lines += [
        "",
        f"Planned calls: {expected}. Saved outcomes: {len(records)}.",
        "Failures and interrupted pending calls are retained in the denominator.",
        "",
        "## Planning and checked substitutions",
        "",
        f"Planning status: **{local.get('planning_status', 'not_run')}**.",
        f"Checked substitutions: **{local.get('checked_substitution_status', 'not_run')}**.",
    ]
    for blocker in local.get("planning_blockers", []):
        lines.append(f"- **{blocker['code']}**: {blocker['detail']}")
    lines += [
        "",
        "## Real-food retrieval",
        "",
        "| Method | Queries with results | Mean known distance | Category agreement | Seconds |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metric in local.get("retrieval", {}).get("methods", {}).items():
        distance = metric["mean_known_distance"]
        category = metric["same_category_fraction"]
        lines.append(
            f"| {name} | {metric['queries_with_results']}/{metric['queries']} | "
            f"{distance if distance is not None else 'unknown'} | "
            f"{category if category is not None else 'unknown'} | "
            f"{metric['retrieval_seconds']:.3f} |"
        )
    lines += [
        "",
        "Catalogue retrieval is transductive and does not establish patient suitability.",
        "",
        "## Semantic review",
        "",
        f"Status: {review.get('state', 'recorded')}.",
        "",
        "| Split | Task | Context | Model | Reviewed | Correct | Supported | Relevant |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in semantic_summary:
        lines.append(
            "| "
            + " | ".join(
                str(row[key])
                for key in (
                    "split",
                    "task",
                    "condition",
                    "model",
                    "reviewed",
                    "correct",
                    "supported",
                    "relevant",
                )
            )
            + " |"
        )
    if result.get("verification"):
        lines += [
            "",
            "## Supporting software verification",
            "",
            str(result["verification"]["counts"]),
            "",
            result["verification"]["scope"],
        ]
    lines += ["", "## Limitations", "", *[f"- {item}" for item in result["limitations"]]]
    (target / "report.md").write_text("\n".join(lines) + "\n")
    return result
