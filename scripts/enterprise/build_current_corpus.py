from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
DEFAULT_SOURCE = ENTERPRISE_DATA_DIR / "processed" / "rag_chunks_clean.jsonl"
DEFAULT_OUTPUT = ENTERPRISE_DATA_DIR / "processed" / "rag_chunks_current.jsonl"
DEFAULT_REPORT = ENTERPRISE_DATA_DIR / "processed" / "rag_chunks_current_report.json"

DEFAULT_ALLOWED_STATUSES = (
    "Còn hiệu lực",
    "Hết hiệu lực một phần",
)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("Đ", "D").replace("đ", "d")


def _normalize_status(status: str) -> str:
    text = _strip_accents(status).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _jsonl_items(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from exc


def build_current_corpus(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    allowed_statuses = tuple(_split_csv(args.allowed_statuses) or DEFAULT_ALLOWED_STATUSES)
    allowed_normalized = {_normalize_status(status) for status in allowed_statuses}

    if not source.exists():
        raise FileNotFoundError(f"Source JSONL not found: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    status_counts = Counter()
    kept_status_counts = Counter()
    skipped_status_counts = Counter()
    topic_counts = Counter()
    kept_doc_ids: set[str] = set()

    with output.open("w", encoding="utf-8") as out:
        for _, item in _jsonl_items(source):
            stats["source_chunks"] += 1
            status = str(item.get("status") or "").strip()
            normalized = _normalize_status(status)
            status_key = status or "<missing>"
            status_counts[status_key] += 1

            if normalized not in allowed_normalized:
                stats["skipped_chunks"] += 1
                skipped_status_counts[status_key] += 1
                continue

            item["retrieval_scope"] = "current"
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            stats["kept_chunks"] += 1
            kept_status_counts[status_key] += 1

            doc_id = str(item.get("canonical_doc_id") or "").strip()
            if doc_id:
                kept_doc_ids.add(doc_id)
            for topic in item.get("topic_labels") or []:
                topic_counts[str(topic)] += 1

            if args.limit and stats["kept_chunks"] >= args.limit:
                break

    stats["kept_documents"] = len(kept_doc_ids)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "output": str(output),
        "allowed_statuses": list(allowed_statuses),
        "stats": dict(stats),
        "status_counts": dict(status_counts),
        "kept_status_counts": dict(kept_status_counts),
        "skipped_status_counts": dict(skipped_status_counts),
        "topic_counts": dict(topic_counts),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build current-law corpus from enterprise clean RAG chunks")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--allowed-statuses",
        default=",".join(DEFAULT_ALLOWED_STATUSES),
        help="Comma-separated statuses to keep. Default keeps current and partially expired documents.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit kept chunks for smoke tests; 0 means all")
    args = parser.parse_args()

    report = build_current_corpus(args)
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))
    print(json.dumps(report["kept_status_counts"], ensure_ascii=False, indent=2))
    print(f"Output: {report['output']}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
