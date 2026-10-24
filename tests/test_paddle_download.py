import importlib.util
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location(
    "download_paddle", Path(__file__).parents[1] / "scripts/download_paddle.py"
)
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)


def test_download_retains_partial_on_retry_and_reuses_complete_wheel(tmp_path, monkeypatch):
    calls = []

    def curl(command, check):
        partial = Path(command[command.index("--output") + 1])
        calls.append(command)
        if len(calls) == 1:
            partial.write_bytes(b"partial download")
            return SimpleNamespace(returncode=28)
        assert partial.read_bytes() == b"partial download"
        assert command[command.index("--continue-at") + 1] == "-"
        with ZipFile(partial, "w") as archive:
            archive.writestr("fixture.txt", "complete")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(downloader.subprocess, "run", curl)
    monkeypatch.setattr(downloader.time, "sleep", lambda seconds: None)
    url = "https://example.test/fixture.whl"
    wheel = downloader.download(url, tmp_path)
    assert wheel.exists()
    assert not wheel.with_suffix(".whl.part").exists()
    assert downloader.download(url, tmp_path) == wheel
    assert len(calls) == 2
