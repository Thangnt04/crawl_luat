from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SCRIPT = PROJECT_ROOT / "scripts" / "test_crawl_sample.py"
ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
PROJECT_VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    env = os.environ.copy()
    env["VBPL_DATA_DIR"] = str(ENTERPRISE_DATA_DIR)
    ENTERPRISE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    python_exec = str(PROJECT_VENV_PYTHON) if PROJECT_VENV_PYTHON.exists() else sys.executable
    cmd = [python_exec, str(SAMPLE_SCRIPT), "--focus", "enterprise", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
