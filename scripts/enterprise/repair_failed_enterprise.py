from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
os.environ["VBPL_DATA_DIR"] = str(ENTERPRISE_DATA_DIR)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (  # noqa: E402
    CHUNKS_JSONL_OUTPUT,
    FULL_JSONL_OUTPUT,
    RAG_READY_JSONL_OUTPUT,
    RAW_FILES_DIR,
    ensure_data_dirs,
)
from crawler.download_files import download_attachments  # noqa: E402
from crawler.parse_detail import build_document_record, extract_doc_id, parse_document_detail  # noqa: E402
from crawler.save_jsonl import (  # noqa: E402
    append_jsonl,
    append_jsonl_items,
    build_chunk_records,
    build_full_record,
    build_rag_ready_record,
)
from scripts.test_crawl_one import (  # noqa: E402
    _build_client,
    _fetch_parsed_detail_from_api,
    _save_raw_html,
)


DEFAULT_FAILED_URLS = [
    "https://vbpl.vn/van-ban/chi-tiet/128613",
    "https://vbpl.vn/van-ban/chi-tiet/60223",
    "https://vbpl.vn/van-ban/chi-tiet/66787",
    "https://vbpl.vn/van-ban/chi-tiet/38544",
    "https://vbpl.vn/van-ban/chi-tiet/18474",
    "https://vbpl.vn/van-ban/chi-tiet/65411",
]


def _scan_existing_doc_ids(path: Path) -> set[str]:
    existing: set[str] = set()
    if not path.exists():
        return existing
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc_id = str(item.get("canonical_doc_id") or "").strip()
            if doc_id:
                existing.add(doc_id)
    return existing


def _scan_chunk_counts(path: Path, doc_ids: set[str]) -> dict[str, int]:
    counts = {doc_id: 0 for doc_id in doc_ids}
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc_id = str(item.get("canonical_doc_id") or "").strip()
            if doc_id in counts:
                counts[doc_id] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair missing enterprise JSONL outputs for failed URLs")
    parser.add_argument("--url", action="append", default=[], help="Specific VBPL detail URL to repair")
    parser.add_argument("--download-files", action="store_true", help="Download attached files while repairing")
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    args = parser.parse_args()

    ensure_data_dirs()
    urls = args.url or DEFAULT_FAILED_URLS
    target_doc_ids = {extract_doc_id(url) for url in urls if extract_doc_id(url)}
    full_ids = _scan_existing_doc_ids(FULL_JSONL_OUTPUT)
    rag_ids = _scan_existing_doc_ids(RAG_READY_JSONL_OUTPUT)
    chunk_counts = _scan_chunk_counts(CHUNKS_JSONL_OUTPUT, target_doc_ids)

    client = _build_client(request_delay_seconds=args.request_delay_seconds)
    repaired = 0
    skipped = 0
    failed = 0

    for url in urls:
        doc_id = extract_doc_id(url)
        if not doc_id:
            client.logger.warning("Skip URL without doc_id: %s", url)
            skipped += 1
            continue

        needs_full = doc_id not in full_ids
        needs_rag = doc_id not in rag_ids
        needs_chunks = chunk_counts.get(doc_id, 0) == 0
        if not (needs_full or needs_rag or needs_chunks):
            client.logger.info("Already complete, skip repair: %s", url)
            skipped += 1
            continue

        try:
            api_parsed = _fetch_parsed_detail_from_api(client, url)
            if api_parsed is None:
                html = client.fetch_html(url)
                raw_html_path = _save_raw_html(url, html)
                parsed = parse_document_detail(url, html)
            else:
                raw_html_path, parsed = api_parsed

            downloaded_files: list[str] = []
            if args.download_files:
                output_dir = RAW_FILES_DIR / doc_id
                downloaded_files = download_attachments(
                    client=client,
                    file_urls=parsed.get("file_urls", []),
                    output_dir=output_dir,
                )

            record = build_document_record(
                page_url=url,
                parsed=parsed,
                raw_html_path=str(raw_html_path),
                downloaded_files=downloaded_files,
            )
            full_record = build_full_record(record)
            rag_record = build_rag_ready_record(record)
            chunk_records = build_chunk_records(record, rag_record)
            rag_record["chunk_count"] = len(chunk_records)

            if needs_chunks:
                append_jsonl_items(CHUNKS_JSONL_OUTPUT, chunk_records)
                chunk_counts[doc_id] = len(chunk_records)
            if needs_rag:
                append_jsonl(RAG_READY_JSONL_OUTPUT, rag_record)
                rag_ids.add(doc_id)
            if needs_full:
                append_jsonl(FULL_JSONL_OUTPUT, full_record)
                full_ids.add(doc_id)

            client.logger.info(
                "Repair complete: %s (full=%s, rag=%s, chunks=%s)",
                url,
                needs_full,
                needs_rag,
                needs_chunks,
            )
            repaired += 1
        except Exception as exc:  # noqa: BLE001
            client.logger.exception("Repair failed for %s: %s", url, exc)
            failed += 1

    client.logger.info("Repair summary: repaired=%s, skipped=%s, failed=%s", repaired, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
