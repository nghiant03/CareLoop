import json
import os
from pathlib import Path

import pytest

from backend.storage_paths import artifact_dir
from evaluation import benchmark, run_eval


def test_output_root_is_configurable_and_does_not_create_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CARELOOP_ARTIFACT_DIR", raising=False)
    monkeypatch.setenv("CARELOOP_DATASET_DIR", str(tmp_path / "datasets"))
    assert artifact_dir("evaluation") == tmp_path / "datasets/outputs/evaluation"
    assert not (tmp_path / "datasets").exists()
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(tmp_path / "external"))
    assert artifact_dir("retrieval") == tmp_path / "external/retrieval"


def test_evaluation_cli_default_and_explicit_output(monkeypatch, tmp_path):
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run_eval, "run_suite", lambda **kwargs: {"meta": {"seed": 42}})
    monkeypatch.setattr(run_eval, "render_report", lambda results: "# Test report\n")
    monkeypatch.setattr(run_eval, "_print_headlines", lambda results: None)
    assert run_eval.main([]) == 0
    output = tmp_path / "runs/evaluation"
    assert not output.parent.exists()
    explicit = tmp_path / "selected"
    assert run_eval.main(["--out-dir", str(explicit)]) == 0
    assert json.loads((explicit / "results.json").read_text()) == {"meta": {"seed": 42}}
    assert (explicit / "EVALUATION.md").read_text() == "# Test report\n"
    in_repo = run_eval.ROOT / "evaluation"
    try:
        run_eval.main(["--out-dir", str(in_repo)])
    except ValueError as exc:
        assert "outside the code checkout" in str(exc)
    else:
        raise AssertionError("Expected ValueError when writing inside repository checkout")


@pytest.mark.parametrize("args", [[], ["--quick"], ["--rerun-benchmark"]])
def test_evaluation_preserves_existing_reports_without_export(monkeypatch, tmp_path, capsys, args):
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(tmp_path / "runs"))
    output = tmp_path / "runs/evaluation"
    output.mkdir(parents=True)
    for name in ("results.json", "EVALUATION.md"):
        (output / name).write_text("Existing report\n")
    calls = []
    results = {"meta": {"seed": 42}}

    def evaluate(**kwargs):
        calls.append(kwargs)
        return results

    def unexpected_report(results):
        raise AssertionError("Report rendering requires an explicit export")

    headlines = []
    monkeypatch.setattr(run_eval, "run_suite", evaluate)
    monkeypatch.setattr(run_eval, "render_report", unexpected_report)
    monkeypatch.setattr(run_eval, "_print_headlines", headlines.append)
    assert run_eval.main(args) == 0
    assert calls == [{
        "rerun_benchmark": "--rerun-benchmark" in args,
        "optimiser_kwargs": {"pop_size": 20, "n_gen": 40} if "--quick" in args else None,
        "max_nhanes_subjects": 200 if "--quick" in args else 600,
    }]
    assert headlines == [results]
    assert "Wrote" not in capsys.readouterr().out
    assert sorted(path.name for path in output.iterdir()) == ["EVALUATION.md", "results.json"]
    for path in output.iterdir():
        assert path.read_text() == "Existing report\n"


def test_no_generated_reports_inside_repository():
    forbidden = [
        run_eval.ROOT / "evaluation/EVALUATION.md",
        run_eval.ROOT / "evaluation/results.json",
        run_eval.ROOT / "backend/optim/benchmark_results.md",
        run_eval.ROOT / "backend/optim/benchmark_wall_time.md",
        run_eval.ROOT / "backend/mining/COMPARISON.md",
        run_eval.ROOT / "backend/app/chat/RETRIEVAL_BENCH.md",
    ]
    for path in forbidden:
        assert not path.exists(), f"Generated report must not live inside repository: {path}"


def test_benchmark_rerun_reads_generated_files_without_mutating_snapshots(monkeypatch, tmp_path):
    root = tmp_path / "runs"
    monkeypatch.setenv("CARELOOP_ARTIFACT_DIR", str(root))
    monkeypatch.setenv("CARELOOP_BENCH_SMOKE", "1")
    published_csv = benchmark._CSV_PATH.read_bytes()
    published_md = benchmark._MD_PATH.read_bytes()

    def generate(command, *, cwd, check, env):
        assert command[-1] == "backend.optim.benchmark"
        assert check and Path(cwd) == benchmark.ROOT
        assert env["CARELOOP_BENCH_SMOKE"] == "0"
        assert env["CARELOOP_ARTIFACT_DIR"] == str(root)
        output = root / "optim"
        output.mkdir(parents=True)
        (output / "benchmark_results.csv").write_bytes(published_csv)
        (output / "benchmark_results.md").write_text("## Recommendation\nGenerated marker\n")

    monkeypatch.setattr(benchmark.subprocess, "run", generate)
    result = benchmark.evaluate_benchmark(rerun_benchmark=True)
    assert result["recommendation"] == "Generated marker"
    assert result["artefacts"]["csv"] == str(root / "optim/benchmark_results.csv")
    assert benchmark._CSV_PATH.read_bytes() == published_csv
    assert benchmark._MD_PATH.read_bytes() == published_md
    assert os.environ["CARELOOP_BENCH_SMOKE"] == "1"
    assert benchmark.evaluate_benchmark()["artefacts"]["csv"] == str(benchmark._CSV_PATH)
