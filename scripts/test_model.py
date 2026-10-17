"""Run the existing model tests in a disposable copy of their data and artifacts."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="peatland-model-tests-") as folder:
        workspace = Path(folder)
        shutil.copytree(ROOT / "b_model", workspace / "b_model", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copytree(ROOT / "data/processed", workspace / "data/processed")
        print("Running model tests in an isolated copy; original data and artifacts are preserved.", flush=True)
        return subprocess.run([sys.executable, "-m", "pytest", "b_model/tests", "-q"], cwd=workspace).returncode


if __name__ == "__main__":
    raise SystemExit(main())
