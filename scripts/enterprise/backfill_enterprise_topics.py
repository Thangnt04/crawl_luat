from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SCRIPT = PROJECT_ROOT / "scripts" / "test_crawl_sample.py"
ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
PROJECT_VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def _build_args(args: argparse.Namespace) -> list[str]:
    cmd = [
        "--focus",
        "enterprise",
        "--max-docs",
        str(args.max_docs),
        "--request-delay-seconds",
        str(args.request_delay_seconds),
        "--max-spurious-interrupts",
        str(args.max_spurious_interrupts),
    ]
    if args.topics.strip():
        cmd.extend(["--enterprise-topics", args.topics.strip()])
    if args.enterprise_keywords.strip():
        cmd.extend(["--enterprise-keywords", args.enterprise_keywords.strip()])
    if args.download_files:
        cmd.append("--download-files")
    if args.incremental:
        cmd.append("--incremental")
    if args.since_date.strip():
        cmd.extend(["--since-date", args.since_date.strip()])
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill dữ liệu doanh nghiệp theo taxonomy mở rộng, ghi vào "
            r"D:\vbpl_data_enterprise và giữ dedupe theo corpus hiện có."
        )
    )
    parser.add_argument("--max-docs", type=int, default=200000)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    parser.add_argument("--max-spurious-interrupts", type=int, default=3)
    parser.add_argument(
        "--topics",
        default="",
        help=(
            "Chỉ backfill một số topic, ví dụ: "
            "ke_toan_kiem_toan,chung_khoan,thue. Bỏ trống để dùng toàn bộ taxonomy."
        ),
    )
    parser.add_argument(
        "--enterprise-keywords",
        default="",
        help="Keyword bổ sung, phân tách bằng dấu phẩy.",
    )
    parser.add_argument("--download-files", action="store_true")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Không khuyến nghị cho backfill thiếu dữ liệu cũ; chỉ dùng khi muốn crawl văn bản mới.",
    )
    parser.add_argument("--since-date", default="")
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Chỉ in command sẽ chạy, không crawl.",
    )
    args = parser.parse_args()

    env = os.environ.copy()
    env["VBPL_DATA_DIR"] = str(ENTERPRISE_DATA_DIR)
    ENTERPRISE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    python_exec = str(PROJECT_VENV_PYTHON) if PROJECT_VENV_PYTHON.exists() else sys.executable
    cmd = [python_exec, str(SAMPLE_SCRIPT), *_build_args(args)]
    print("VBPL_DATA_DIR=", ENTERPRISE_DATA_DIR, sep="")
    print("Command:", " ".join(f'"{part}"' if " " in part else part for part in cmd))
    if args.print_command:
        return 0
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
