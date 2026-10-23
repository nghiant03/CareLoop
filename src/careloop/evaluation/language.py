"""Frozen extraction and cited-answer experiments using the application prompts."""

import itertools
import json
import re
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from careloop import answers
from careloop.evaluation.storage import claim, digest, now, read, write
from careloop.evidence import extraction
from careloop.inference import CompletionOptions, InferenceClient, InferenceError, Settings

MODELS = ["glm-5.3", "qwen3.8-max", "deepseek-v4-pro-0813", "kimi-k3"]
OPTIONS = CompletionOptions(response_mode="json_object", reasoning_effort="high", max_tokens=8192)


def rule_score(result, expected):
    """Order-independent exact structured-field matching; prose is reviewed separately."""
    actual = result["rules"]
    references = expected.get(
        "expected_rules", expected.get("reference_extraction", {}).get("rules", [])
    )
    core_fields = ("kind", "subject", "amount", "upper", "unit", "basis")

    def match(a, b):
        return all(
            a["action"].get(key) == value
            for key, value in b["action"].items()
            if key in core_fields
        )

    def normalize(values):
        return sorted(json.dumps(v, sort_keys=True) for v in values)

    pairs = []
    for permutation in itertools.permutations(
        range(len(actual)), min(len(actual), len(references))
    ):
        for subset in itertools.combinations(range(len(references)), len(permutation)):
            candidate = list(zip(permutation, subset, strict=True))
            if sum(match(actual[a], references[b]) for a, b in candidate) > sum(
                match(actual[a], references[b]) for a, b in pairs
            ):
                pairs = candidate
    matched = [(a, b) for a, b in pairs if match(actual[a], references[b])]
    checks = {}
    for a, b in matched:
        ref, output = references[b], actual[a]
        prefix = str(b)
        for field in ("applicability", "exceptions"):
            if field in ref:
                checks[f"{prefix}:{field}"] = normalize(output[field]) == normalize(ref[field])
        if "blocker_required" in ref or "blockers" in ref:
            required = ref.get("blocker_required", bool(ref.get("blockers")))
            checks[f"{prefix}:blocker"] = bool(output["blockers"]) == required
        for field, patterns in ref.get("required_patterns", {}).items():
            text = json.dumps(output.get(field, ""))
            for index, pattern in enumerate(patterns):
                checks[f"{prefix}:{field}:{index}"] = bool(re.search(pattern, text, re.I))
    return {
        "reference_actions": len(references),
        "returned_actions": len(actual),
        "matched_actions": len(matched),
        "action_precision": len(matched) / len(actual)
        if actual
        else (1.0 if not references else 0.0),
        "action_recall": len(matched) / len(references) if references else 1.0,
        "no_extra_actions": len(matched) == len(actual),
        "structured_checks": checks,
        "bounded_pass": len(matched) == len(actual) == len(references) and all(checks.values()),
        "semantic_review_required": True,
    }


def answer_score(result, expected, supplied_ids, ablated=False):
    reference = expected.get("expected", expected.get("reference_answer"))
    insufficient = True if ablated else reference["insufficient_evidence"]
    checks = {
        "needs_clinician": result["needs_clinician"] == reference["needs_clinician"],
        "insufficient_evidence": result["insufficient_evidence"] == insufficient,
        "citation_ids_valid": all(c["source_id"] in supplied_ids for c in result["citations"]),
    }
    if insufficient:
        checks["no_citations_for_missing_evidence"] = not result["citations"]
    else:
        expected_ids = reference.get(
            "source_ids",
            reference.get(
                "supporting_source_ids", expected.get("source_ids", expected.get("passage_ids"))
            ),
        )
        checks["reference_source_cited"] = bool(
            set(expected_ids) & {c["source_id"] for c in result["citations"]}
        )
    if not ablated:
        for index, pattern in enumerate(reference.get("required_patterns", [])):
            checks[f"required:{index}"] = bool(re.search(pattern, result["answer"], re.I))
        for index, pattern in enumerate(reference.get("forbidden_patterns", [])):
            checks[f"forbidden:{index}"] = not re.search(pattern, result["answer"], re.I)
    return {
        "checks": checks,
        "bounded_pass": all(checks.values()),
        "semantic_review_required": True,
        "scoring_scope": "Flags, source identities and declared text checks; not claim entailment",
    }


def tasks(corpus, split, models=MODELS):
    documents = {d["id"]: d for d in corpus["documents"]}
    passages = {p["id"]: p for p in corpus["passages"]}
    result = []
    for model in models:
        for passage in passages.values():
            if documents[passage["document_id"]]["split"] != split:
                continue
            content = {"location": passage["location"], "content": passage["content"]}
            result.append(
                {
                    "task": "extraction",
                    "case_id": passage["id"],
                    "model": model,
                    "split": split,
                    "condition": "source_provided",
                    "reference": passage,
                    "passage": content,
                    "payload": extraction.request(model, content, OPTIONS),
                    "prompt_version": extraction.PROMPT_VERSION,
                }
            )
        for question in corpus["questions"]:
            if question["split"] != split:
                continue
            sources = [
                {"id": identity, "text": passages[identity]["content"]}
                for identity in question["passage_ids"]
            ]
            conditions = ["grounded"]
            if question.get("ablation", False):
                conditions.append("evidence_removed")
            for condition in conditions:
                selected = sources if condition == "grounded" else []
                result.append(
                    {
                        "task": "chat",
                        "case_id": question["id"],
                        "model": model,
                        "split": split,
                        "condition": condition,
                        "reference": question,
                        "sources": selected,
                        "payload": answers.request(model, question["question"], selected, OPTIONS),
                        "prompt_version": answers.PROMPT_VERSION,
                    }
                )
    return result


def execute_task(task, root, endpoint_hash):
    identity = digest({"task": task, "endpoint_sha256": endpoint_hash})
    path = root / "requests" / f"{identity}.json"
    metadata = {"id": identity, "task": task, "endpoint_sha256": endpoint_hash}
    if not claim(path, metadata):
        return read(path)
    started = perf_counter()
    outcome = {**metadata, "started_at": read(path)["started_at"]}
    try:
        with InferenceClient(Settings.load()) as client:
            response = client.complete(**task["payload"])
        outcome["response"] = response
        if task["task"] == "extraction":
            result = extraction.parse(response, task["passage"]).model_dump(mode="json")
            scores = rule_score(result, task["reference"])
        else:
            result = answers.parse(response, task["sources"]).model_dump(mode="json")
            scores = answer_score(
                result,
                task["reference"],
                [s["id"] for s in task["sources"]],
                task["condition"] == "evidence_removed",
            )
        outcome.update(state="completed", result=result, scores=scores)
    except InferenceError as exc:
        outcome.update(state="failed", error=str(exc), stage=exc.stage)
    except Exception as exc:
        outcome.update(state="failed", error=type(exc).__name__, stage="evaluation")
    outcome.update(seconds=perf_counter() - started, finished_at=now())
    write(path, outcome)
    return outcome


def run_tasks(task_list, root, endpoint_hash, workers=4):
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(lambda task: execute_task(task, root, endpoint_hash), task_list))
