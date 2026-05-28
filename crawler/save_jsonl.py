from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _normalize_for_match(text: str) -> str:
    text = _strip_accents(text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


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

    return {
        "id": record.get("id", ""),
        "title": record.get("title", ""),
        "document_type": record.get("document_type", ""),
        "document_number": record.get("document_number", ""),
        "summary": record.get("summary", ""),
        "issuing_agency": record.get("issuing_agency", ""),
        "signer": record.get("signer", ""),
        "issued_date": record.get("issued_date", ""),
        "effective_date": record.get("effective_date", ""),
        "expired_date": record.get("expired_date", ""),
        "updated_date": record.get("updated_date", ""),
        "status": record.get("status", ""),
        "field": record.get("field", ""),
        "source_url": record.get("source_url", ""),
        "pdf_urls": classified["pdf_urls"],
        "doc_urls": classified["doc_urls"],
        "docx_urls": classified["docx_urls"],
        "html_urls": classified["html_urls"],
        "json_snapshot_urls": classified["json_snapshot_urls"],
        "content_html": content_html,
        "content_clean": content_clean,
        "header_issuing_body": header_fields["header_issuing_body"],
        "header_national_title": header_fields["header_national_title"],
        "header_document_code": header_fields["header_document_code"],
        "header_place_date": header_fields["header_place_date"],
        "header_legal_bases": header_fields["header_legal_bases"],
        "crawl_time": record.get("crawl_time", ""),
    }


def load_existing_index(full_path: Path) -> tuple[set[str], set[str], str]:
    ids: set[str] = set()
    urls: set[str] = set()
    latest_date = ""
    if not full_path.exists():
        return ids, urls, latest_date
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
            for key in ("updated_date", "issued_date"):
                value = str(item.get(key) or "").strip()
                if value and value > latest_date:
                    latest_date = value
    return ids, urls, latest_date


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
) -> None:
    append_jsonl(full_path, build_full_record(record))
    append_jsonl(rag_path, build_rag_ready_record(record))

