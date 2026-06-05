from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    CHUNKS_JSONL_OUTPUT,
    DATA_DIR,
    FULL_JSONL_OUTPUT,
    RAG_READY_JSONL_OUTPUT,
    RAW_FILES_DIR,
    RAW_HTML_DIR,
    RAW_LIST_PAGES_DIR,
    Settings,
    ensure_data_dirs,
    setup_logging,
)
from crawler.discover_urls import discover_document_urls
from crawler.discover_urls import discover_document_urls_from_api
from crawler.download_files import download_attachments
from crawler.enterprise_taxonomy import (
    enterprise_keywords_for_topics,
    match_enterprise_topics,
    resolve_topic_slugs,
    split_csv,
    topic_choices_text,
)
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


def _normalize_datetime(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("Z", "+00:00")
    try:
        if "T" in raw or "+" in raw:
            dt = datetime.fromisoformat(raw)
        else:
            dt = datetime.fromisoformat(f"{raw[:10]}T00:00:00")
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except ValueError:
        return ""

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


def _enterprise_match_fields(parsed: dict) -> dict[str, object]:
    return {
        "title": parsed.get("title", ""),
        "summary": parsed.get("summary", ""),
        "field": parsed.get("field", ""),
        "document_type": parsed.get("document_type", ""),
        "document_number": parsed.get("document_number", ""),
        "issuing_agency": parsed.get("issuing_agency", ""),
    }


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


def _fetch_parsed_detail_from_api(client: HttpClient, source_url: str) -> tuple[Path, dict] | None:
    doc_id = extract_doc_id(source_url)
    if not doc_id:
        return None
    try:
        detail_resp = client.get_json(f"{API_BASE_URL}/qtdc/public/doc/{doc_id}")
    except Exception as exc:  # noqa: BLE001
        client.logger.warning("API detail failed for %s (doc_id=%s), fallback HTML: %s", source_url, doc_id, exc)
        return None
    detail_data = detail_resp.get("data") or {}
    if not isinstance(detail_data, dict) or not detail_data:
        client.logger.warning("API detail empty for %s (doc_id=%s), fallback HTML", source_url, doc_id)
        return None

    raw_html_path = _save_raw_api_payload(doc_id, detail_data)
    file_items: list[dict] = []
    try:
        files_resp = client.get_json(
            f"{API_BASE_URL}/qtdc/public/doc/minio/buckets/vbpl/folders/{doc_id}/files"
        )
        file_items = files_resp.get("data") or []
    except Exception as exc:  # noqa: BLE001
        client.logger.warning("API files list failed for %s (doc_id=%s): %s", source_url, doc_id, exc)

    parsed = parse_document_detail_from_api(
        doc_id=doc_id,
        detail_data=detail_data,
        file_items=file_items,
        source_url=source_url,
    )
    _ensure_content_quality(parsed, client)
    return raw_html_path, parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl sample VBPL documents")
    parser.add_argument(
        "--max-docs",
        type=int,
        default=5,
        help="Number of sample docs to crawl (recommended: 5-10)",
    )
    parser.add_argument(
        "--use-html-list",
        action="store_true",
        help="Use HTML list pages instead of API (fallback mode)",
    )
    parser.add_argument(
        "--download-files",
        action="store_true",
        help="Download attached files (pdf/doc/docx)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only crawl documents newer than the latest date in full JSONL",
    )
    parser.add_argument(
        "--since-date",
        default="",
        help="Optional cutoff (YYYY-MM-DD or ISO datetime). Crawl docs newer than this checkpoint",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between requests for safe large crawling",
    )
    parser.add_argument(
        "--incremental-overlap-days",
        type=int,
        default=1,
        help="When auto-using latest checkpoint, step back this many days to avoid missing same-day updates",
    )
    parser.add_argument(
        "--max-spurious-interrupts",
        type=int,
        default=1,
        help="How many unexpected KeyboardInterrupts to ignore before stopping gracefully",
    )
    parser.add_argument(
        "--focus",
        choices=["all", "enterprise"],
        default="all",
        help="Crawl focus mode. Use 'enterprise' to keep only enterprise-related documents",
    )
    parser.add_argument(
        "--enterprise-keywords",
        default="",
        help="Optional comma-separated extra keywords for enterprise mode",
    )
    parser.add_argument(
        "--enterprise-topics",
        default="",
        help=f"Optional comma-separated topic slugs to backfill only selected topics. Choices: {topic_choices_text()}",
    )
    args = parser.parse_args()

    ensure_data_dirs()
    client = _build_client(request_delay_seconds=args.request_delay_seconds)
    client.logger.info("Run config: focus=%s, VBPL_DATA_DIR=%s", args.focus, DATA_DIR)
    enterprise_keywords: list[str] = []
    enterprise_extra_keywords: list[str] = []
    enterprise_topic_slugs: list[str] = []
    if args.focus == "enterprise":
        enterprise_extra_keywords = split_csv(args.enterprise_keywords)
        try:
            enterprise_topic_slugs = resolve_topic_slugs(split_csv(args.enterprise_topics))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        enterprise_keywords = enterprise_keywords_for_topics(
            topic_slugs=enterprise_topic_slugs,
            extra_keywords=enterprise_extra_keywords,
        )
        topic_log = ",".join(enterprise_topic_slugs) if enterprise_topic_slugs else "all"
        client.logger.info(
            "Enterprise mode enabled with topics=%s, keywords=%s, extra_keywords=%s",
            topic_log,
            len(enterprise_keywords),
            len(enterprise_extra_keywords),
        )
    existing_ids, existing_urls, latest_checkpoint = load_existing_index(FULL_JSONL_OUTPUT)
    existing_doc_ids: set[str] = set()
    for existing_url in existing_urls:
        doc_id = extract_doc_id(existing_url)
        if doc_id:
            existing_doc_ids.add(doc_id)
    if existing_doc_ids:
        client.logger.info("Loaded %s canonical doc IDs from existing index", len(existing_doc_ids))
    cutoff_date = args.since_date.strip()
    auto_checkpoint = args.incremental and not cutoff_date
    if auto_checkpoint:
        cutoff_date = latest_checkpoint
    cutoff_date = _normalize_datetime(cutoff_date)
    if auto_checkpoint and cutoff_date:
        try:
            overlap_days = max(0, int(args.incremental_overlap_days))
            dt = datetime.fromisoformat(cutoff_date)
            # List API dates are usually date-granularity; floor to day to avoid missing same-day rows.
            dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0)
            if overlap_days > 0:
                dt = dt - timedelta(days=overlap_days)
            cutoff_date = dt.isoformat(timespec="seconds")
            client.logger.info(
                "Applied incremental overlap: %s day(s), adjusted cutoff_date=%s",
                overlap_days,
                cutoff_date,
            )
        except ValueError:
            pass
    now_str = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
    if cutoff_date and cutoff_date > now_str:
        client.logger.warning(
            "cutoff_date=%s is in the future relative to now=%s, clamping to now",
            cutoff_date,
            now_str,
        )
        cutoff_date = now_str
    if cutoff_date:
        client.logger.info("Incremental mode enabled with cutoff_date=%s", cutoff_date)

    doc_urls: list[str]
    try:
        if args.use_html_list:
            from config import DEFAULT_LIST_URLS

            doc_urls = discover_document_urls(
                client=client,
                list_page_urls=DEFAULT_LIST_URLS,
                raw_list_pages_dir=RAW_LIST_PAGES_DIR,
                max_documents=args.max_docs,
            )
        else:
            doc_urls = discover_document_urls_from_api(
                client=client,
                raw_list_pages_dir=RAW_LIST_PAGES_DIR,
                max_documents=args.max_docs,
                since_date=cutoff_date,
                skip_doc_ids=existing_doc_ids,
                include_title_keywords=enterprise_keywords if args.focus == "enterprise" else None,
            )
    except KeyboardInterrupt:
        client.logger.warning("KeyboardInterrupt while discovering URL list. Stop gracefully.")
        return
    client.logger.info("Total discovered URLs for sample crawl: %s", len(doc_urls))

    max_spurious_interrupts = max(0, int(args.max_spurious_interrupts))
    consecutive_interrupts = 0
    saved_count = 0
    duplicate_count = 0
    failed_count = 0
    filtered_out_count = 0

    for idx, url in enumerate(doc_urls, start=1):
        try:
            api_parsed = _fetch_parsed_detail_from_api(client, url)
            if api_parsed is None:
                html = client.fetch_html(url)
                raw_html_path = _save_raw_html(url, html)
                parsed = parse_document_detail(url, html)
            else:
                raw_html_path, parsed = api_parsed
            client.logger.info(
                "Candidate fields (%s): %s",
                url,
                json.dumps(parsed.get("candidate_fields", {}), ensure_ascii=False),
            )
            if args.focus == "enterprise":
                enterprise_match = match_enterprise_topics(
                    _enterprise_match_fields(parsed),
                    topic_slugs=enterprise_topic_slugs,
                    extra_keywords=enterprise_extra_keywords,
                )
                if not enterprise_match["is_match"]:
                    client.logger.info("Skip non-enterprise record: %s", url)
                    filtered_out_count += 1
                    consecutive_interrupts = 0
                    continue
                parsed["topic_labels"] = enterprise_match["topic_labels"]
                parsed["topic_names"] = enterprise_match["topic_names"]
                parsed["matched_keywords"] = enterprise_match["matched_keywords"]
                parsed["matched_fields"] = enterprise_match["matched_fields"]
                client.logger.info(
                    "Enterprise match (%s): topics=%s keywords=%s",
                    url,
                    parsed["topic_labels"],
                    parsed["matched_keywords"][:12],
                )

            downloaded_files: list[str] = []
            if args.download_files:
                doc_id = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
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
            if should_skip_duplicate(record, existing_ids, existing_urls):
                client.logger.info("Skip duplicate: %s", record.get("source_url"))
                duplicate_count += 1
                consecutive_interrupts = 0
                continue
            append_full_and_rag(FULL_JSONL_OUTPUT, RAG_READY_JSONL_OUTPUT, record, CHUNKS_JSONL_OUTPUT)
            update_index(record, existing_ids, existing_urls)
            client.logger.info("Saved record: %s", url)
            saved_count += 1
            consecutive_interrupts = 0
        except KeyboardInterrupt:
            consecutive_interrupts += 1
            client.logger.warning(
                "KeyboardInterrupt while processing %s (progress %s/%s, interrupt %s/%s)",
                url,
                idx,
                len(doc_urls),
                consecutive_interrupts,
                max_spurious_interrupts,
            )
            if consecutive_interrupts <= max_spurious_interrupts:
                client.logger.warning("Treating as spurious interrupt and continuing crawl")
                continue
            client.logger.warning(
                "Interrupt threshold exceeded. Stop gracefully. Re-run the same command to continue."
            )
            break
        except Exception as exc:  # noqa: BLE001
            client.logger.exception("Failed processing %s: %s", url, exc)
            failed_count += 1

    client.logger.info(
        "Run summary: discovered=%s, saved=%s, duplicates=%s, filtered_out=%s, failed=%s",
        len(doc_urls),
        saved_count,
        duplicate_count,
        filtered_out_count,
        failed_count,
    )


if __name__ == "__main__":
    main()
