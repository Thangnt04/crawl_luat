from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    FULL_JSONL_OUTPUT,
    RAG_READY_JSONL_OUTPUT,
    RAW_FILES_DIR,
    RAW_HTML_DIR,
    Settings,
    ensure_data_dirs,
    setup_logging,
)
from crawler.download_files import download_attachments
from crawler.http_client import HttpClient, HttpClientConfig
from crawler.clean_text import clean_legal_text
from crawler.parse_detail import (
    build_document_record,
    extract_doc_id,
    parse_document_detail,
    parse_document_detail_from_api,
)
from crawler.save_jsonl import (
    append_full_and_rag,
    load_existing_index,
    should_skip_duplicate,
    update_index,
)

API_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api"


def _build_client(request_delay_seconds: float) -> HttpClient:
    settings = Settings()
    logger = setup_logging()
    return HttpClient(
        config=HttpClientConfig(
            user_agent=settings.user_agent,
            timeout_seconds=settings.timeout_seconds,
            retry_total=settings.retry_total,
            retry_backoff_factor=settings.retry_backoff_factor,
            request_delay_seconds=request_delay_seconds,
        ),
        logger=logger,
    )


def _save_raw_html(url: str, html: str) -> Path:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    file_path = RAW_HTML_DIR / f"{doc_id}.html"
    file_path.write_text(html, encoding="utf-8")
    return file_path


def _save_raw_api_payload(doc_id: str, detail_data: dict) -> Path:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    file_path = RAW_HTML_DIR / f"{doc_id}_api.json"
    file_path.write_text(json.dumps(detail_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


def _ensure_content_quality(parsed: dict, client: HttpClient, min_chars: int = 800) -> None:
    content_text = str(parsed.get("content_text") or "")
    full_html = str(parsed.get("full_html_content") or "")
    if len(content_text) >= min_chars and full_html:
        return
    for attachment in parsed.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        if str(attachment.get("file_type") or "").lower() != "html":
            continue
        html_url = str(attachment.get("url") or "").strip()
        if not html_url:
            continue
        try:
            html_content = client.fetch_html(html_url)
            soup = BeautifulSoup(html_content, "lxml")
            cleaned = clean_legal_text(soup.get_text("\n", strip=True))
            if len(cleaned) >= len(content_text):
                parsed["full_html_content"] = html_content
                parsed["content_text"] = cleaned
            return
        except Exception:  # noqa: BLE001
            continue


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl one VBPL document URL")
    parser.add_argument("--url", required=True, help="Detail URL from vbpl.vn")
    parser.add_argument(
        "--download-files",
        action="store_true",
        help="Download attached files (pdf/doc/docx) if found",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between requests for safe large crawling",
    )
    args = parser.parse_args()

    ensure_data_dirs()
    client = _build_client(request_delay_seconds=args.request_delay_seconds)
    existing_ids, existing_urls, _ = load_existing_index(FULL_JSONL_OUTPUT)
    doc_id = extract_doc_id(args.url)
    raw_html_path = RAW_HTML_DIR / "not_available_api_mode.html"
    parsed: dict

    try:
        if doc_id:
            detail_resp = client.get_json(f"{API_BASE_URL}/qtdc/public/doc/{doc_id}")
            detail_data = detail_resp.get("data") or {}
            raw_html_path = _save_raw_api_payload(doc_id, detail_data)
            files_resp = client.get_json(
                f"{API_BASE_URL}/qtdc/public/doc/minio/buckets/vbpl/folders/{doc_id}/files"
            )
            file_items = files_resp.get("data") or []
            parsed = parse_document_detail_from_api(
                doc_id=doc_id,
                detail_data=detail_data,
                file_items=file_items,
            )
            _ensure_content_quality(parsed, client)
        else:
            html = client.fetch_html(args.url)
            raw_html_path = _save_raw_html(args.url, html)
            parsed = parse_document_detail(args.url, html)
    except Exception as exc:  # noqa: BLE001
        client.logger.exception("Cannot crawl detail URL %s: %s", args.url, exc)
        return

    client.logger.info(
        "Candidate fields detected for manual review: %s",
        json.dumps(parsed.get("candidate_fields", {}), ensure_ascii=False),
    )

    downloaded_files: list[str] = []
    if args.download_files:
        file_id = hashlib.sha1(args.url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        output_dir = RAW_FILES_DIR / file_id
        downloaded_files = download_attachments(
            client=client,
            file_urls=parsed.get("file_urls", []),
            output_dir=output_dir,
        )

    record = build_document_record(
        page_url=args.url,
        parsed=parsed,
        raw_html_path=str(raw_html_path),
        downloaded_files=downloaded_files,
    )
    if should_skip_duplicate(record, existing_ids, existing_urls):
        client.logger.info("Skip duplicate: %s", record.get("source_url"))
        return
    append_full_and_rag(FULL_JSONL_OUTPUT, RAG_READY_JSONL_OUTPUT, record)
    update_index(record, existing_ids, existing_urls)
    client.logger.info("Saved full record to %s", FULL_JSONL_OUTPUT)
    client.logger.info("Saved rag-ready record to %s", RAG_READY_JSONL_OUTPUT)


if __name__ == "__main__":
    main()
