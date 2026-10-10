"""Failure-path and serialized-reader regressions without artifact writes."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from evaluation.q_ablation import CompositionEvaluator, composition_ga
from evaluation.q_groundedness import _claim_sources_consistent, _claims_supported
from evaluation.report import _q6_ablation_rows, render_report
from evaluation.run_eval import _source_revision
from evaluation.test_ablation import ABLATION_POOL, _envelope
from shared.envelope_schema import CitationSource, ExclusionFlag, ExclusionKind


@pytest.mark.parametrize("exhausted", [False, True])
def test_composition_empty_and_exclusion_exhausted_pools(exhausted):
    env = _envelope()
    dishes = []
    if exhausted:
        dishes = ABLATION_POOL
        env = env.model_copy(update={"exclusions": [
            ExclusionFlag(kind=ExclusionKind.DISH_CATEGORY, value=category,
                          reason="test exclusion", citation=CitationSource(
                              rule_id="R", guideline="G", section="S"))
            for category in {dish.category for dish in dishes}
        ]})
    ev = CompositionEvaluator(env, dishes)
    assert ev.size_m == ev.size_s == 0
    assert ev.nut_m.shape == ev.nut_s.shape == (0, 10)
    assert ev.nut_m.dtype == ev.nut_s.dtype == np.dtype(float)
    result = composition_ga(ev, seed=0, pop_size=2, n_gen=1)
    assert result == {"front": [], "note": "empty MAIN/SIDE pool",
                      "generations": 0, "archive_size": 0}


@pytest.mark.parametrize("jj_result", ["missing", "nonzero", "empty"])
def test_source_revision_falls_back_to_git(monkeypatch, jj_result):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[0] == "jj":
            if jj_result == "missing":
                raise FileNotFoundError("jj")
            return SimpleNamespace(returncode=1 if jj_result == "nonzero" else 0,
                                   stdout="")
        return SimpleNamespace(returncode=0, stdout="git-revision\n")

    monkeypatch.setattr(subprocess, "run", run)
    assert _source_revision() == "git-revision"
    assert [command[0] for command in commands] == ["jj", "git"]


def test_source_revision_unavailable_is_explicit(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError("VCS unavailable")

    monkeypatch.setattr(subprocess, "run", run)
    assert _source_revision() == "unavailable (no accessible VCS revision)"


def test_report_renders_actual_per_day_compliance_and_reads_old_metrics():
    results = json.loads((Path(__file__).parent / "results.json").read_text())
    q3 = results["q3_constraint_satisfaction"]
    patient = next(row for row in q3["per_patient"] if row.get("attempted"))
    patient["per_day_hard_compliant"] = True
    q3["per_patient"] = [patient]
    report = render_report(results)
    q3_report = report.split("## Q3 — Constraint satisfaction", 1)[1].split("## Q4", 1)[0]
    table_row = next(line for line in q3_report.splitlines()
                     if line.startswith(f"| {patient['patient_id']} |")
                     and len(line.split("|")) == 10)
    assert table_row.split("|")[6].strip() == "True"
    patient["per_day_hard_compliant"] = False
    assert table_row.replace("True", "False") in render_report(results)
    # Old pooled raw gaps have no recoverable common unit. Never relabel them.
    old = _q6_ablation_rows({"scalar": {"mean_daily_shortfall": 123.0}})
    assert old[0][4] == "n/a"
    new = _q6_ablation_rows({"scalar": {"mean_daily_rel_shortfall_pct": 12.5}})
    assert new[0][4] == "12.5"


def test_groundedness_name_retains_callable_compatibility_and_limits():
    assert _claims_supported is _claim_sources_consistent
    response = {"answer": "An arbitrary dish assertion.", "claims": [
        {"text": "An arbitrary dish assertion.", "source": "dish", "chunk_id": "dish:example"}
    ]}
    # The intentionally weaker metric checks source identity, not food facts.
    assert _claim_sources_consistent(response, None)
