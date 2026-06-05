from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    append_jsonl_items(path, [item])


def _is_retryable_write_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "errno", None) == 13 or getattr(exc, "winerror", None) in {
        5,
        32,
        33,
    }


def append_jsonl_items(path: Path, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False) + "\n" for item in items]
    retries = max(0, int(os.getenv("VBPL_JSONL_WRITE_RETRIES", "12")))
    base_delay = max(0.05, float(os.getenv("VBPL_JSONL_WRITE_RETRY_BASE_SECONDS", "0.25")))

    for attempt in range(retries + 1):
        try:
            with path.open("a", encoding="utf-8") as f:
                f.writelines(lines)
            return
        except OSError as exc:
            if not _is_retryable_write_error(exc) or attempt >= retries:
                raise
            time.sleep(base_delay * min(2**attempt, 16))


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("Đ", "D").replace("đ", "d")


def _normalize_for_match(text: str) -> str:
    text = _strip_accents(text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _normalize_date_only(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    # Accept both date-only and datetime strings, always return YYYY-MM-DD.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return ""


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        if "T" in raw or "+" in raw:
            dt = datetime.fromisoformat(raw)
        else:
            d = date.fromisoformat(raw[:10])
            dt = datetime(d.year, d.month, d.day, 0, 0, 0)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _normalize_datetime_to_iso(value: str) -> str:
    dt = _parse_iso_datetime(value)
    return dt.isoformat(timespec="seconds") if dt else ""


def _is_meaningful_title(title: str) -> bool:
    val = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    if not val:
        return False
    generic_tokens = {
        "văn bản pháp luật",
        "van ban phap luat",
        "văn bản pháp luật | cơ sở dữ liệu quốc gia về pháp luật",
        "van ban phap luat | co so du lieu quoc gia ve phap luat",
    }
    return val not in generic_tokens


def _compute_quality_flags(record: dict[str, Any], content_clean: str) -> list[str]:
    flags: list[str] = []
    if not _is_meaningful_title(str(record.get("title") or "")):
        flags.append("generic_title")
    if not str(record.get("document_type") or "").strip():
        flags.append("missing_document_type")
    if not str(record.get("document_number") or "").strip():
        flags.append("missing_document_number")
    if not str(record.get("issued_date") or "").strip():
        flags.append("missing_issued_date")
    if len(content_clean) < 200:
        flags.append("short_content")
    return flags


def _compute_data_quality_score(record: dict[str, Any], content_clean: str) -> int:
    score = 0
    if _is_meaningful_title(str(record.get("title") or "")):
        score += 15
    if str(record.get("document_type") or "").strip():
        score += 10
    if str(record.get("document_number") or "").strip():
        score += 10
    if str(record.get("issued_date") or "").strip() or str(record.get("issued_at") or "").strip():
        score += 10
    if str(record.get("issuing_agency") or "").strip():
        score += 5
    if str(record.get("source_url") or "").strip():
        score += 5
    if len(content_clean) >= 1500:
        score += 45
    elif len(content_clean) >= 800:
        score += 35
    elif len(content_clean) >= 300:
        score += 25
    elif len(content_clean) >= 120:
        score += 15
    return min(score, 100)


def _collect_all_file_urls(record: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in record.get("attachments", []):
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    for url in record.get("file_urls", []):
        val = str(url).strip()
        if val and val not in seen:
            seen.add(val)
            urls.append(val)
    return urls


def _classify_urls(urls: list[str]) -> dict[str, list[str]]:
    classified = {
        "pdf_urls": [],
        "doc_urls": [],
        "docx_urls": [],
        "html_urls": [],
        "json_snapshot_urls": [],
    }
    for url in urls:
        lower = url.lower()
        if ".pdf" in lower:
            classified["pdf_urls"].append(url)
        elif ".docx" in lower:
            classified["docx_urls"].append(url)
        elif ".doc" in lower:
            classified["doc_urls"].append(url)
        elif ".html" in lower:
            classified["html_urls"].append(url)
        elif ".json" in lower:
            classified["json_snapshot_urls"].append(url)
    return classified


def _extract_content_html(record: dict[str, Any]) -> str:
    html = str(record.get("full_html_content") or "").strip()
    if html:
        return html
    text = str(record.get("content_text") or "").strip()
    if "<" in text and ">" in text:
        return text
    return ""


def _extract_header_from_clean_text(content_clean: str) -> dict[str, Any]:
    lines = [line.strip() for line in content_clean.splitlines() if line.strip()]
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()

    header_issuing_body = ""
    header_national_title = ""
    header_document_code = ""
    header_place_date = ""

    code_match = re.search(r"Số\s*:\s*([0-9]+/\d{4}/[A-Za-zÀ-ỹĐđ0-9\-]+)", text, re.IGNORECASE)
    if code_match:
        header_document_code = f"Số: {code_match.group(1)}"

    national_match = re.search(r"CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", text, re.IGNORECASE)
    if national_match:
        header_national_title = national_match.group(0)

    for line in lines[:20]:
        normalized = _normalize_for_match(line)
        if re.search(r"uy ban|hoi dong|chinh phu", normalized):
            header_issuing_body = line
            break

    for line in lines[:30]:
        if re.search(r",\s*ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}", line, re.IGNORECASE):
            header_place_date = re.sub(r"^.*Hạnh phúc\s+", "", line, flags=re.IGNORECASE).strip()
            break

    legal_bases = re.findall(r"(Căn cứ[^;\n]+;|Theo đề nghị[^;\n]+;)", content_clean, flags=re.IGNORECASE)

    return {
        "header_issuing_body": header_issuing_body,
        "header_national_title": header_national_title,
        "header_document_code": header_document_code,
        "header_place_date": header_place_date,
        "header_legal_bases": legal_bases[:12],
    }


def _clean_content_from_html(content_html: str) -> str:
    if not content_html:
        return ""
    soup = BeautifulSoup(content_html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    raw_blocks: list[str] = []
    for selector in ("p", "li", "td", "th", "h1", "h2", "h3", "h4"):
        for node in soup.find_all(selector):
            text = node.get_text(" ", strip=True)
            if text:
                raw_blocks.append(text)
    if not raw_blocks:
        raw_blocks = [soup.get_text(" ", strip=True)]

    def normalize_line(line: str) -> str:
        line = line.replace("\u00a0", " ")
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"(\d)\s*/\s*", r"\1/", line)
        line = re.sub(r"/\s+", "/", line)
        line = re.sub(r"(\d{3})\s+(\d)(?=/)", r"\1\2", line)
        line = re.sub(r"\b(20\d)\s+(\d)\b", r"\1\2", line)
        line = re.sub(r"\s+([,;:.])", r"\1", line)
        line = re.sub(r"\b([A-Za-zÀ-ỹĐđ])\s+([A-Za-zÀ-ỹĐđ])\b", r"\1\2", line)
        line = re.sub(r"\b(Theođềnghị)\b", "Theo đề nghị", line, flags=re.IGNORECASE)
        return line

    blocks = [normalize_line(line) for line in raw_blocks if normalize_line(line)]
    heading_re = re.compile(r"^(QUYẾT ĐỊNH|NGHỊ ĐỊNH|THÔNG TƯ|LUẬT)\b", re.IGNORECASE)
    article_re = re.compile(r"^Điều\s+\d+[\.:]?", re.IGNORECASE)
    clause_re = re.compile(r"^\d+\.\s+")
    point_re = re.compile(r"^[a-zA-Z]\)\s+")

    merged: list[str] = []
    for line in blocks:
        if not merged:
            merged.append(line)
            continue
        prev = merged[-1]
        is_structural = bool(
            heading_re.match(line) or article_re.match(line) or clause_re.match(line) or point_re.match(line)
        )
        if is_structural:
            merged.append(line)
            continue
        if len(line) <= 22 or prev.endswith((",", ";", ":", "-", "/")):
            merged[-1] = re.sub(r"\s+", " ", f"{prev} {line}").strip()
        else:
            merged.append(line)

    text = "\n".join(merged)
    text = re.sub(r"(\d)\s+/\s*([A-Za-zÀ-ỹĐđ])", r"\1/\2", text)
    text = re.sub(r"\b(20\d)\s+(\d)\b", r"\1\2", text)
    text = re.sub(r"\s+([,;:.])", r"\1", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"(\d)/\s+(\d)", r"\1/\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def build_full_record(record: dict[str, Any]) -> dict[str, Any]:
    full_record = dict(record)
    full_record["file_urls"] = _collect_all_file_urls(record)
    full_record["content_html"] = _extract_content_html(record)
    return full_record


def build_rag_ready_record(record: dict[str, Any]) -> dict[str, Any]:
    all_urls = _collect_all_file_urls(record)
    classified = _classify_urls(all_urls)
    content_html = _extract_content_html(record)
    content_clean = _clean_content_from_html(content_html)
    if not content_clean:
        content_clean = str(record.get("content_text") or "").strip()
        content_clean = re.sub(r"[ \t]+", " ", content_clean)
        content_clean = re.sub(r"\n{3,}", "\n\n", content_clean).strip()
    header_fields = _extract_header_from_clean_text(content_clean)
    quality_score = _compute_data_quality_score(record, content_clean)
    quality_flags = _compute_quality_flags(record, content_clean)

    return {
        "id": record.get("id", ""),
        "canonical_doc_id": record.get("canonical_doc_id", ""),
        "id_type": record.get("id_type", ""),
        "title": record.get("title", ""),
        "document_type": record.get("document_type", ""),
        "document_number": record.get("document_number", ""),
        "summary": record.get("summary", ""),
        "issuing_agency": record.get("issuing_agency", ""),
        "signer": record.get("signer", ""),
        "issued_date": record.get("issued_date", ""),
        "issued_at": record.get("issued_at", ""),
        "effective_date": record.get("effective_date", ""),
        "effective_at": record.get("effective_at", ""),
        "expired_date": record.get("expired_date", ""),
        "expired_at": record.get("expired_at", ""),
        "gazette_date": record.get("gazette_date", ""),
        "gazette_at": record.get("gazette_at", ""),
        "updated_date": record.get("updated_date", ""),
        "updated_at": record.get("updated_at", ""),
        "status": record.get("status", ""),
        "field": record.get("field", ""),
        "source_url": record.get("source_url", ""),
        "pdf_urls": classified["pdf_urls"],
        "doc_urls": classified["doc_urls"],
        "docx_urls": classified["docx_urls"],
        "html_urls": classified["html_urls"],
        "json_snapshot_urls": classified["json_snapshot_urls"],
        "topic_labels": record.get("topic_labels", []),
        "topic_names": record.get("topic_names", []),
        "matched_keywords": record.get("matched_keywords", []),
        "matched_fields": record.get("matched_fields", {}),
        "content_clean": content_clean,
        "quality_score": quality_score,
        "quality_flags": quality_flags,
        "header_issuing_body": header_fields["header_issuing_body"],
        "header_national_title": header_fields["header_national_title"],
        "header_document_code": header_fields["header_document_code"],
        "header_place_date": header_fields["header_place_date"],
        "header_legal_bases": header_fields["header_legal_bases"],
        "crawl_time": record.get("crawl_time", ""),
    }


def _split_text_with_overlap(text: str, max_chars: int = 1400, overlap: int = 220) -> list[str]:
    normalized = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    chunks: list[str] = []
    start = 0
    step = max(max_chars - overlap, 200)
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(normalized):
            break
        start += step
    return chunks


def _build_structured_chunks(
    record: dict[str, Any],
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    articles = record.get("articles")
    if not isinstance(articles, list) or not articles:
        return chunks

    chunk_idx = 0

    def push_chunk(
        text: str,
        level: str,
        article_number: str = "",
        clause_number: str = "",
        point_key: str = "",
    ) -> None:
        nonlocal chunk_idx
        cleaned = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
        if len(cleaned) < 80:
            return
        chunk_idx += 1
        chunks.append(
            {
                **base_meta,
                "chunk_id": f"{base_meta.get('id', '')}:{chunk_idx:05d}",
                "level": level,
                "article_number": article_number,
                "clause_number": clause_number,
                "point_key": point_key,
                "text": cleaned,
                "char_count": len(cleaned),
            }
        )

    for article in articles:
        if not isinstance(article, dict):
            continue
        article_number = str(article.get("article_number") or "").strip()
        article_title = str(article.get("article_title") or "").strip()
        article_content = article.get("content") or []
        if isinstance(article_content, list):
            article_content_text = "\n".join(str(item).strip() for item in article_content if str(item).strip())
        else:
            article_content_text = str(article_content).strip()
        article_header = f"Điều {article_number}".strip() if article_number else "Điều"
        if article_title:
            article_header = f"{article_header}. {article_title}"
        if article_content_text:
            push_chunk(
                text=f"{article_header}\n{article_content_text}",
                level="article",
                article_number=article_number,
            )

        for clause in article.get("clauses") or []:
            if not isinstance(clause, dict):
                continue
            clause_number = str(clause.get("clause_number") or "").strip()
            clause_content = str(clause.get("content") or "").strip()
            clause_header = f"Khoản {clause_number}" if clause_number else "Khoản"
            if clause_content:
                push_chunk(
                    text=f"{article_header}\n{clause_header}. {clause_content}",
                    level="clause",
                    article_number=article_number,
                    clause_number=clause_number,
                )
            for point in clause.get("points") or []:
                if not isinstance(point, dict):
                    continue
                point_key = str(point.get("point_key") or "").strip()
                point_content = str(point.get("content") or "").strip()
                if not point_content:
                    continue
                point_header = f"Điểm {point_key}" if point_key else "Điểm"
                push_chunk(
                    text=f"{article_header}\n{clause_header}\n{point_header}. {point_content}",
                    level="point",
                    article_number=article_number,
                    clause_number=clause_number,
                    point_key=point_key,
                )
    return chunks


def build_chunk_records(record: dict[str, Any], rag_record: dict[str, Any]) -> list[dict[str, Any]]:
    base_meta = {
        "id": record.get("id", ""),
        "canonical_doc_id": record.get("canonical_doc_id", ""),
        "id_type": record.get("id_type", ""),
        "title": record.get("title", ""),
        "document_type": record.get("document_type", ""),
        "document_number": record.get("document_number", ""),
        "issued_date": record.get("issued_date", ""),
        "effective_date": record.get("effective_date", ""),
        "status": record.get("status", ""),
        "field": record.get("field", ""),
        "source_url": record.get("source_url", ""),
        "topic_labels": record.get("topic_labels", []),
        "topic_names": record.get("topic_names", []),
        "matched_keywords": record.get("matched_keywords", []),
        "crawl_time": record.get("crawl_time", ""),
        "quality_score": rag_record.get("quality_score", 0),
    }
    chunks = _build_structured_chunks(record, base_meta)
    if chunks:
        return chunks

    fallback_text = str(rag_record.get("content_clean") or "").strip()
    fallback_chunks: list[dict[str, Any]] = []
    for idx, piece in enumerate(_split_text_with_overlap(fallback_text), start=1):
        fallback_chunks.append(
            {
                **base_meta,
                "chunk_id": f"{base_meta.get('id', '')}:{idx:05d}",
                "level": "fallback",
                "article_number": "",
                "clause_number": "",
                "point_key": "",
                "text": piece,
                "char_count": len(piece),
            }
        )
    return fallback_chunks


def load_existing_index(full_path: Path) -> tuple[set[str], set[str], str]:
    ids: set[str] = set()
    urls: set[str] = set()
    latest_checkpoint = ""
    latest_dt: datetime | None = None
    if not full_path.exists():
        return ids, urls, latest_checkpoint
    with full_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_id = str(item.get("id") or "").strip()
            item_url = str(item.get("source_url") or "").strip()
            if item_id:
                ids.add(item_id)
            if item_url:
                urls.add(item_url)
            for key in ("updated_at", "issued_at", "updated_date", "issued_date"):
                value = str(item.get(key) or "")
                normalized = _normalize_datetime_to_iso(value)
                if not normalized:
                    only_date = _normalize_date_only(value)
                    normalized = f"{only_date}T00:00:00" if only_date else ""
                candidate_dt = _parse_iso_datetime(normalized)
                if candidate_dt and (latest_dt is None or candidate_dt > latest_dt):
                    latest_dt = candidate_dt
                    latest_checkpoint = normalized
    return ids, urls, latest_checkpoint


def should_skip_duplicate(record: dict[str, Any], ids: set[str], urls: set[str]) -> bool:
    item_id = str(record.get("id") or "").strip()
    item_url = str(record.get("source_url") or "").strip()
    if item_id and item_id in ids:
        return True
    if item_url and item_url in urls:
        return True
    return False


def update_index(record: dict[str, Any], ids: set[str], urls: set[str]) -> None:
    item_id = str(record.get("id") or "").strip()
    item_url = str(record.get("source_url") or "").strip()
    if item_id:
        ids.add(item_id)
    if item_url:
        urls.add(item_url)


def append_full_and_rag(
    full_path: Path,
    rag_path: Path,
    record: dict[str, Any],
    chunks_path: Path | None = None,
) -> None:
    full_record = build_full_record(record)
    rag_record = build_rag_ready_record(record)
    chunk_records = build_chunk_records(record, rag_record)
    rag_record["chunk_count"] = len(chunk_records)

    if chunks_path:
        append_jsonl_items(chunks_path, chunk_records)
    append_jsonl(rag_path, rag_record)
    append_jsonl(full_path, full_record)

