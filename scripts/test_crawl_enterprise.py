from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE_LAUNCHER = PROJECT_ROOT / "scripts" / "enterprise" / "run_enterprise_crawl.py"


def main() -> int:
    cmd = [sys.executable, str(ENTERPRISE_LAUNCHER), *sys.argv[1:]]
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
