"""Download the locked GPU wheel with resumable retries into a build cache."""

import hashlib
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


def download(url, cache):
    directory = cache / hashlib.sha256(url.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / Path(urlsplit(url).path).name
    if wheel.exists():
        return wheel
    partial = wheel.with_suffix(".whl.part")
    for attempt in range(8):
        print(f"GPU wheel download attempt {attempt + 1}; resuming {partial}", flush=True)
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--show-error",
                "--silent",
                "--connect-timeout",
                "30",
                "--speed-limit",
                "1024",
                "--speed-time",
                "90",
                "--max-time",
                "1800",
                "--continue-at",
                "-",
                "--output",
                str(partial),
                url,
            ],
            check=False,
        )
        # A complete .part can remain if the build stopped before its rename.
        try:
            with zipfile.ZipFile(partial) as archive:
                valid = archive.testzip() is None
        except (OSError, zipfile.BadZipFile, EOFError):
            valid = False
        if valid:
            partial.replace(wheel)
            return wheel
        if result.returncode == 0:
            # Completed but corrupt: appending cannot repair it.
            partial.unlink(missing_ok=True)
        if attempt < 7:
            time.sleep(5)
    raise RuntimeError(f"GPU download incomplete; retry the build to resume {partial}")


def main():
    lock = tomllib.loads(Path("uv.lock").read_text())
    package = next(p for p in lock["package"] if p["name"] == "paddlepaddle-gpu")
    wheels = [
        w["url"] for w in package["wheels"] if w["url"].endswith("-cp312-cp312-linux_x86_64.whl")
    ]
    if len(wheels) != 1:
        raise RuntimeError("Expected one locked Python 3.12 Linux x86_64 GPU wheel")
    wheel = download(wheels[0], Path("/root/.cache/careloop-wheels"))
    if "--install" in sys.argv:
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                "/app/.venv/bin/python",
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
