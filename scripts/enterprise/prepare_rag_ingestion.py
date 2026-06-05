from __future__ import annotations

import argparse
from collections import Counter
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import heapq
import json
import logging
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader


logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pypdf._reader").setLevel(logging.ERROR)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.enterprise_taxonomy import match_enterprise_topics  # noqa: E402

ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
API_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api"
SAMPLE_QUERIES = [
    "doanh nghiệp siêu nhỏ chế độ kế toán",
    "đăng ký kinh doanh ngành nghề",
    "doanh nghiệp bán hàng đa cấp",
    "hộ kinh doanh sau đăng ký thành lập",
]


@dataclass(frozen=True)
class ChunkConfig:
    max_chars: int
    overlap_chars: int
    min_chars: int


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("Đ", "D").replace("đ", "d")


def _normalize_for_match(text: str) -> str:
    text = _strip_accents(text).lower()
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(text: str) -> str:
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_chunks(chunks: list[str], config: ChunkConfig) -> list[str]:
    normalized: list[str] = []
    step = max(config.max_chars - config.overlap_chars, config.max_chars // 2)

    for raw_chunk in chunks:
        chunk = _clean_text(raw_chunk)
        if not chunk:
            continue

        pieces = [chunk]
        if len(chunk) > config.max_chars:
            pieces = [
                chunk[start : start + config.max_chars].strip()
                for start in range(0, len(chunk), step)
            ]

        for piece in pieces:
            piece = _clean_text(piece)
            if not piece:
                continue
            if len(piece) < config.min_chars:
                if normalized and len(normalized[-1]) + 1 + len(piece) <= config.max_chars:
                    normalized[-1] = f"{normalized[-1]}\n{piece}"
                continue
            if len(piece) > config.max_chars:
                piece = piece[: config.max_chars].strip()
            normalized.append(piece)

    return normalized


def _jsonl_items(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from exc


def _is_retryable_file_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "errno", None) == 13 or getattr(exc, "winerror", None) in {
        5,
        32,
        33,
    }


def _retry_delay(attempt: int) -> float:
    base_delay = max(0.05, float(os.getenv("VBPL_JSONL_WRITE_RETRY_BASE_SECONDS", "0.25")))
    return base_delay * min(2**attempt, 16)


def _open_text_with_retry(path: Path, mode: str):
    retries = max(0, int(os.getenv("VBPL_JSONL_WRITE_RETRIES", "12")))
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries + 1):
        try:
            return path.open(mode, encoding="utf-8")
        except OSError as exc:
            if not _is_retryable_file_error(exc) or attempt >= retries:
                raise
            time.sleep(_retry_delay(attempt))


def _write_text_with_retry(path: Path, text: str) -> None:
    with _open_text_with_retry(path, "w") as f:
        f.write(text)


def _unlink_with_retry(path: Path) -> None:
    retries = max(0, int(os.getenv("VBPL_JSONL_WRITE_RETRIES", "12")))
    for attempt in range(retries + 1):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if not _is_retryable_file_error(exc) or attempt >= retries:
                raise
            time.sleep(_retry_delay(attempt))


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None
        self._retries = max(0, int(os.getenv("VBPL_JSONL_WRITE_RETRIES", "12")))

    def __enter__(self) -> "JsonlWriter":
        self._file = _open_text_with_retry(self.path, "w")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._file:
            self._file.close()
            self._file = None

    def write(self, item: dict[str, Any]) -> None:
        line = json.dumps(item, ensure_ascii=False) + "\n"
        for attempt in range(self._retries + 1):
            try:
                if self._file is None:
                    self._file = _open_text_with_retry(self.path, "a")
                self._file.write(line)
                return
            except OSError as exc:
                if not _is_retryable_file_error(exc) or attempt >= self._retries:
                    raise
                if self._file:
                    with contextlib.suppress(Exception):
                        self._file.close()
                    self._file = None
                time.sleep(_retry_delay(attempt))


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    line = json.dumps(item, ensure_ascii=False) + "\n"
    with _open_text_with_retry(path, "a") as f:
        f.write(line)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [raw]
    return []


def _topic_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    cached = doc.get("_topic_metadata")
    if isinstance(cached, dict):
        return cached

    labels = _as_list(doc.get("topic_labels"))
    names = _as_list(doc.get("topic_names"))
    keywords = _as_list(doc.get("matched_keywords"))
    if labels:
        result = {
            "topic_labels": labels,
            "topic_names": names,
            "matched_keywords": keywords,
        }
        doc["_topic_metadata"] = result
        return result

    topic_match = match_enterprise_topics(
        {
            "title": doc.get("title", ""),
            "summary": doc.get("summary", ""),
            "field": doc.get("field", ""),
            "document_type": doc.get("document_type", ""),
            "document_number": doc.get("document_number", ""),
            "issuing_agency": doc.get("issuing_agency", ""),
            "content_clean": str(doc.get("content_clean") or "")[:20000],
        }
    )
    result = {
        "topic_labels": topic_match["topic_labels"],
        "topic_names": topic_match["topic_names"],
        "matched_keywords": topic_match["matched_keywords"],
    }
    doc["_topic_metadata"] = result
    return result


def _base_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    topic_meta = _topic_metadata(doc)
    return {
        "id": doc.get("id", ""),
        "canonical_doc_id": doc.get("canonical_doc_id", ""),
        "title": doc.get("title", ""),
        "document_type": doc.get("document_type", ""),
        "document_number": doc.get("document_number", ""),
        "issued_date": doc.get("issued_date", ""),
        "effective_date": doc.get("effective_date", ""),
        "status": doc.get("status", ""),
        "field": doc.get("field", ""),
        "source_url": doc.get("source_url", ""),
        "topic_labels": topic_meta["topic_labels"],
        "topic_names": topic_meta["topic_names"],
        "matched_keywords": topic_meta["matched_keywords"],
        "quality_score": doc.get("quality_score", 0),
    }


def _split_text(text: str, config: ChunkConfig) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    if len(text) <= config.max_chars:
        return _normalize_chunks([text], config)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in re.split(r"(?<=[.!?。;:])\s+", text) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [text[i : i + config.max_chars] for i in range(0, len(text), config.max_chars)]

    chunks: list[str] = []
    current = ""
    for part in paragraphs:
        if len(part) > config.max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            step = max(config.max_chars - config.overlap_chars, config.max_chars // 2)
            for start in range(0, len(part), step):
                piece = part[start : start + config.max_chars].strip()
                if len(piece) >= config.min_chars:
                    chunks.append(piece)
            continue
        candidate = f"{current}\n{part}".strip() if current else part
        if len(candidate) <= config.max_chars:
            current = candidate
            continue
        if len(current) >= config.min_chars:
            chunks.append(current.strip())
        if config.overlap_chars > 0 and chunks:
            overlap = chunks[-1][-config.overlap_chars :].strip()
            current = f"{overlap}\n{part}".strip()
        else:
            current = part
    if len(current) >= config.min_chars:
        chunks.append(current.strip())
    return _normalize_chunks(chunks, config)


def _clean_chunk_record(
    doc: dict[str, Any],
    text: str,
    source: str,
    source_level: str,
    source_index: int,
    piece_index: int,
    config: ChunkConfig,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _base_metadata(doc)
    doc_id = str(meta.get("canonical_doc_id") or meta.get("id") or "unknown")
    chunk_id = f"{doc_id}:{source}:{source_index:05d}:{piece_index:03d}"
    record = {
        **meta,
        "chunk_id": chunk_id,
        "source": source,
        "source_level": source_level,
        "article_number": "",
        "clause_number": "",
        "point_key": "",
        "text": text,
        "char_count": len(text),
        "token_estimate": max(1, len(text) // 4),
        "needs_ocr": False,
    }
    if extra:
        record.update({k: v for k, v in extra.items() if v is not None})
    return record


def _refresh_pdf_urls(doc_id: str, timeout: int) -> list[str]:
    url = f"{API_BASE_URL}/qtdc/public/doc/minio/buckets/vbpl/folders/{doc_id}/files"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    items = (response.json().get("data") or [])
    pdf_urls: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("fileName") or item.get("originalFileName") or "").lower()
        presigned = str(item.get("presignedUrl") or "").strip()
        if presigned and ".pdf" in name:
            pdf_urls.append(presigned)
    return pdf_urls


def _download_pdf_bytes(pdf_url: str, timeout: int, max_bytes: int) -> bytes:
    with requests.get(pdf_url, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and max_bytes and int(content_length) > max_bytes:
            raise ValueError("pdf_too_large")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            total += len(chunk)
            if max_bytes and total > max_bytes:
                raise ValueError("pdf_too_large")
            chunks.append(chunk)
        return b"".join(chunks)


def _extract_pdf_text(
    doc: dict[str, Any],
    timeout: int,
    max_bytes: int,
    max_pages: int,
    pdf_url_limit: int,
) -> tuple[str, str, str]:
    doc_id = str(doc.get("canonical_doc_id") or "").strip()
    pdf_urls = list(doc.get("pdf_urls") or [])
    last_issue = "no_pdf_url"
    if doc_id:
        try:
            refreshed = _refresh_pdf_urls(doc_id, timeout=timeout)
            if refreshed:
                pdf_urls = refreshed
        except Exception:
            pass
    seen_urls: set[str] = set()
    unique_pdf_urls: list[str] = []
    for pdf_url in pdf_urls:
        if pdf_url and pdf_url not in seen_urls:
            seen_urls.add(pdf_url)
            unique_pdf_urls.append(pdf_url)
    if pdf_url_limit:
        unique_pdf_urls = unique_pdf_urls[:pdf_url_limit]

    for pdf_url in unique_pdf_urls:
        try:
            pdf_bytes = _download_pdf_bytes(pdf_url, timeout=timeout, max_bytes=max_bytes)
            with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stderr(devnull):
                reader = PdfReader(BytesIO(pdf_bytes), strict=False)
                pages: list[str] = []
                for page_index, page in enumerate(reader.pages):
                    if max_pages and page_index >= max_pages:
                        break
                    pages.append(page.extract_text() or "")
            text = _clean_text("\n\n".join(pages))
            if text:
                return text, pdf_url, ""
            last_issue = "pdf_empty_text"
        except ValueError as exc:
            last_issue = str(exc) or "pdf_extract_failed"
        except Exception:
            last_issue = "pdf_extract_failed"
            continue
    return "", "", last_issue


def _load_documents(rag_path: Path, max_docs: int) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for item in _jsonl_items(rag_path):
        doc_id = str(item.get("canonical_doc_id") or "").strip()
        if not doc_id:
            continue
        docs[doc_id] = item
        if max_docs and len(docs) >= max_docs:
            break
    return docs


def _query_score(title: str, body: str, normalized_query: str, query_terms: list[str], query_bigrams: list[str]) -> int:
    text = f"{title} {body}".strip()
    score = 0
    if normalized_query and normalized_query in text:
        score += 50
    score += sum(8 for bigram in query_bigrams if bigram in text)
    score += sum(4 for term in query_terms if term in title)
    score += sum(1 for term in query_terms if term in body)
    return score


def _query_features(query: str) -> tuple[str, list[str], list[str]]:
    normalized_query = _normalize_for_match(query)
    query_terms = [term for term in normalized_query.split() if len(term) >= 3]
    query_bigrams = [
        f"{query_terms[index]} {query_terms[index + 1]}"
        for index in range(len(query_terms) - 1)
    ]
    return normalized_query, query_terms, query_bigrams


def _top_results_for_queries(output_path: Path, queries: list[str], limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    features = {query: _query_features(query) for query in queries}
    heaps: dict[str, list[tuple[int, int, dict[str, Any]]]] = {query: [] for query in queries}

    for idx, item in enumerate(_jsonl_items(output_path) or []):
        title = _normalize_for_match(str(item.get("title", "")))
        body = _normalize_for_match(str(item.get("text", "")))
        for query, (normalized_query, query_terms, query_bigrams) in features.items():
            score = _query_score(title, body, normalized_query, query_terms, query_bigrams)
            if score <= 0:
                continue
            result = {
                "score": score,
                "canonical_doc_id": item.get("canonical_doc_id", ""),
                "title": item.get("title", ""),
                "chunk_id": item.get("chunk_id", ""),
                "source_url": item.get("source_url", ""),
            }
            entry = (score, -idx, result)
            heap = heaps[query]
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            else:
                heapq.heappushpop(heap, entry)

    return {
        query: [item for _, _, item in sorted(heap, reverse=True)]
        for query, heap in heaps.items()
    }


def _top_results_for_query(output_path: Path, query: str, limit: int = 5) -> list[dict[str, Any]]:
    normalized_query, query_terms, query_bigrams = _query_features(query)
    heap: list[tuple[int, int, dict[str, Any]]] = []
    for idx, item in enumerate(_jsonl_items(output_path) or []):
        title = _normalize_for_match(str(item.get("title", "")))
        body = _normalize_for_match(str(item.get("text", "")))
        score = _query_score(title, body, normalized_query, query_terms, query_bigrams)
        if score <= 0:
            continue
        result = {
            "score": score,
            "canonical_doc_id": item.get("canonical_doc_id", ""),
            "title": item.get("title", ""),
            "chunk_id": item.get("chunk_id", ""),
            "source_url": item.get("source_url", ""),
        }
        entry = (score, -idx, result)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
        else:
            heapq.heappushpop(heap, entry)
    return [item for _, _, item in sorted(heap, reverse=True)]


def prepare_ingestion(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = Path(args.data_dir).expanduser().resolve()
    processed_dir = data_dir / "processed"
    rag_path = processed_dir / "legal_documents_rag_ready.jsonl"
    chunks_path = processed_dir / "legal_documents_chunks.jsonl"
    output_path = processed_dir / "rag_chunks_clean.jsonl"
    issues_path = processed_dir / "rag_ingestion_issues.jsonl"
    report_path = processed_dir / "rag_ingestion_report.json"
    config = ChunkConfig(args.max_chars, args.overlap_chars, args.min_chars)

    docs = _load_documents(rag_path, max_docs=args.max_docs)
    _unlink_with_retry(output_path)
    _unlink_with_retry(issues_path)

    stats = Counter()
    docs_with_output: set[str] = set()
    pdf_docs_processed = 0
    char_lengths: list[int] = []

    with _open_text_with_retry(output_path, "w") as out, JsonlWriter(issues_path) as issues_out:
        source_index_by_doc: Counter[str] = Counter()
        for chunk in _jsonl_items(chunks_path):
            doc_id = str(chunk.get("canonical_doc_id") or "").strip()
            doc = docs.get(doc_id)
            if not doc:
                continue
            source_index_by_doc[doc_id] += 1
            source_index = source_index_by_doc[doc_id]
            text = _clean_text(str(chunk.get("text") or ""))
            emitted_for_chunk = 0
            for piece_index, piece in enumerate(_split_text(text, config), start=1):
                record = _clean_chunk_record(
                    doc,
                    text=piece,
                    source="crawler_chunk",
                    source_level=str(chunk.get("level") or "unknown"),
                    source_index=source_index,
                    piece_index=piece_index,
                    config=config,
                    extra={
                        "article_number": chunk.get("article_number", ""),
                        "clause_number": chunk.get("clause_number", ""),
                        "point_key": chunk.get("point_key", ""),
                    },
                )
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                emitted_for_chunk += 1
                char_lengths.append(record["char_count"])
            if emitted_for_chunk:
                docs_with_output.add(doc_id)

        stats["documents_from_existing_chunks"] = len(docs_with_output)

        for doc_id, doc in docs.items():
            stats["documents_seen"] += 1
            if doc_id in docs_with_output:
                continue

            emitted_for_doc = 0
            content_clean = _clean_text(str(doc.get("content_clean") or ""))
            if content_clean:
                stats["documents_from_content_clean"] += 1
                for piece_index, piece in enumerate(_split_text(content_clean, config), start=1):
                    record = _clean_chunk_record(
                        doc,
                        text=piece,
                        source="content_clean",
                        source_level="document",
                        source_index=1,
                        piece_index=piece_index,
                        config=config,
                    )
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    emitted_for_doc += 1
                    char_lengths.append(record["char_count"])
                if emitted_for_doc:
                    docs_with_output.add(doc_id)
                continue

            pdf_urls = doc.get("pdf_urls") or []
            if args.skip_pdf_extraction and pdf_urls:
                pdf_extract_issue = "pdf_extract_skipped"
                stats[pdf_extract_issue] += 1
            elif pdf_urls and (not args.max_pdf_docs or pdf_docs_processed < args.max_pdf_docs):
                stats["pdf_only_documents_attempted"] += 1
                pdf_docs_processed += 1
                pdf_text, pdf_url, pdf_extract_issue = _extract_pdf_text(
                    doc,
                    timeout=args.pdf_timeout_seconds,
                    max_bytes=args.max_pdf_bytes,
                    max_pages=args.max_pdf_pages,
                    pdf_url_limit=args.pdf_url_limit,
                )
                if pdf_text:
                    stats["pdf_documents_extracted"] += 1
                    for piece_index, piece in enumerate(_split_text(pdf_text, config), start=1):
                        record = _clean_chunk_record(
                            doc,
                            text=piece,
                            source="pdf_text",
                            source_level="document",
                            source_index=1,
                            piece_index=piece_index,
                            config=config,
                            extra={"pdf_url": pdf_url},
                        )
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        emitted_for_doc += 1
                        char_lengths.append(record["char_count"])
                    if emitted_for_doc:
                        docs_with_output.add(doc_id)
                        continue
                if pdf_extract_issue:
                    stats[pdf_extract_issue] += 1
            else:
                pdf_extract_issue = "pdf_extract_not_attempted" if pdf_urls else ""

            issue = {
                **_base_metadata(doc),
                "issue": "needs_ocr" if pdf_urls else "missing_text",
                "pdf_url_count": len(pdf_urls),
                "pdf_extract_issue": pdf_extract_issue,
            }
            issues_out.write(issue)
            stats[issue["issue"]] += 1
            if args.request_delay_seconds > 0:
                time.sleep(args.request_delay_seconds)

    stats["documents_with_clean_chunks"] = len(docs_with_output)
    stats["documents_without_clean_chunks"] = len(docs) - len(docs_with_output)
    stats["clean_chunks_written"] = sum(1 for _ in _jsonl_items(output_path))
    stats["source_documents_total"] = len(docs)

    char_lengths.sort()
    char_stats = {}
    if char_lengths:
        char_stats = {
            "min": char_lengths[0],
            "p50": char_lengths[len(char_lengths) // 2],
            "p90": char_lengths[int(len(char_lengths) * 0.9)],
            "p99": char_lengths[int(len(char_lengths) * 0.99)],
            "max": char_lengths[-1],
            "under_min_chars": sum(1 for value in char_lengths if value < args.min_chars),
            "over_max_chars": sum(1 for value in char_lengths if value > args.max_chars),
        }

    retrieval_samples = _top_results_for_queries(output_path, SAMPLE_QUERIES, limit=5)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "output_path": str(output_path),
        "issues_path": str(issues_path),
        "stats": dict(stats),
        "chunk_char_stats": char_stats,
        "retrieval_smoke_tests": retrieval_samples,
        "config": {
            "max_chars": args.max_chars,
            "overlap_chars": args.overlap_chars,
            "min_chars": args.min_chars,
            "max_docs": args.max_docs,
            "max_pdf_docs": args.max_pdf_docs,
            "pdf_timeout_seconds": args.pdf_timeout_seconds,
            "max_pdf_bytes": args.max_pdf_bytes,
            "max_pdf_pages": args.max_pdf_pages,
            "pdf_url_limit": args.pdf_url_limit,
            "skip_pdf_extraction": args.skip_pdf_extraction,
        },
    }
    _write_text_with_retry(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare clean RAG chunks from enterprise VBPL crawl output")
    parser.add_argument("--data-dir", default=str(ENTERPRISE_DATA_DIR))
    parser.add_argument("--max-docs", type=int, default=0, help="Limit docs for smoke tests; 0 means all")
    parser.add_argument("--max-pdf-docs", type=int, default=0, help="Limit PDF extraction attempts; 0 means all")
    parser.add_argument("--max-chars", type=int, default=1400)
    parser.add_argument("--overlap-chars", type=int, default=180)
    parser.add_argument("--min-chars", type=int, default=40)
    parser.add_argument("--pdf-timeout-seconds", type=int, default=12)
    parser.add_argument("--max-pdf-bytes", type=int, default=20_000_000)
    parser.add_argument("--max-pdf-pages", type=int, default=80)
    parser.add_argument("--pdf-url-limit", type=int, default=1, help="PDF URLs to try per document; 0 means all")
    parser.add_argument("--skip-pdf-extraction", action="store_true", help="Skip PDF text extraction and mark PDF-only docs as needs_ocr")
    parser.add_argument("--request-delay-seconds", type=float, default=0.05)
    args = parser.parse_args()

    report = prepare_ingestion(args)
    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))
    print(json.dumps(report["chunk_char_stats"], ensure_ascii=False, indent=2))
    print(f"Output: {report['output_path']}")
    print(f"Issues: {report['issues_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
