"""New evaluation runs must not rewrite published evidence snapshots."""

import json
import os
from pathlib import Path

from backend.storage_paths import artifact_dir
from evaluation import q_benchmark, run_eval


def test_output_root_is_configurable_and_does_not_create_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CARELOOP_ARTIFACT_DIR", raising=False)
    assert artifact_dir("evaluation") == tmp_path / "artifacts/evaluation"
    assert not (tmp_path / "artifacts").exists()
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(tmp_path / "external"))
    assert artifact_dir("retrieval") == tmp_path / "external/retrieval"


def test_evaluation_cli_default_and_explicit_output(monkeypatch, tmp_path):
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run_eval, "run_suite", lambda **kwargs: {"meta": {"seed": 42}})
    monkeypatch.setattr(run_eval, "render_report", lambda results: "# Test report\n")
    monkeypatch.setattr(run_eval, "_print_headlines", lambda results: None)
    assert run_eval.main([]) == 0
    output = tmp_path / "runs/evaluation"
    assert json.loads((output / "results.json").read_text()) == {"meta": {"seed": 42}}
    assert (output / "EVALUATION.md").read_text() == "# Test report\n"
    explicit = tmp_path / "selected"
    assert run_eval.main(["--out-dir", str(explicit)]) == 0
    assert (explicit / "results.json").exists()


def test_q4_rerun_reads_generated_files_without_mutating_snapshots(monkeypatch, tmp_path):
    root = tmp_path / "runs"
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(root))
    monkeypatch.setenv("CARELOOP_BENCH_SMOKE", "1")
    published_csv = q_benchmark._CSV_PATH.read_bytes()
    published_md = q_benchmark._MD_PATH.read_bytes()

    def generate(command, *, cwd, check, env):
        assert command[-1] == "backend.optim.benchmark"
        assert check and Path(cwd) == q_benchmark.ROOT
        assert env["CARELOOP_BENCH_SMOKE"] == "0"
        assert env["CARELOOP_ARTIFACT_DIR"] == str(root)
        output = root / "optim"
        output.mkdir(parents=True)
        (output / "benchmark_results.csv").write_bytes(published_csv)
        (output / "benchmark_results.md").write_text("## Recommendation\nGenerated marker\n")

    monkeypatch.setattr(q_benchmark.subprocess, "run", generate)
    result = q_benchmark.evaluate_q4(rerun_benchmark=True)
    assert result["recommendation"] == "Generated marker"
    assert result["artefacts"]["csv"] == str(root / "optim/benchmark_results.csv")
    assert q_benchmark._CSV_PATH.read_bytes() == published_csv
    assert q_benchmark._MD_PATH.read_bytes() == published_md
    assert os.environ["CARELOOP_BENCH_SMOKE"] == "1"
    assert q_benchmark.evaluate_q4()["artefacts"]["csv"] == "backend/optim/benchmark_results.csv"
