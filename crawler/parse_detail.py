from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .clean_text import clean_legal_text

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
DOC_DETAIL_ID_PATTERN = re.compile(r"/van-ban/chi-tiet/([^/?#]+)", re.IGNORECASE)
CLAUSE_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
POINT_RE = re.compile(r"^\s*([a-zA-Z])\)\s+(.*)$")

RELATION_TYPE_MAP = {
    1: "abrogates",
    2: "translation",
    3: "basis",
    4: "referenced_by",
    5: "suspends_execution",
    6: "corrects",
    7: "consolidates",
    8: "guides_application",
    9: "detail_guiding_regulation",
    10: "amends_supplements",
    11: "temporarily_suspends_effect",
    12: "replaces",
    13: "supplements",
    14: "explains",
    15: "referenced_text",
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("Đ", "D").replace("đ", "d")


def _normalize_key(text: str) -> str:
    text = _strip_accents(text or "").lower()
    text = re.sub(r"[\s:/\-_,.;]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_for_match(text: str) -> str:
    text = _strip_accents(text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _pick_first(values: list[str]) -> str:
    for value in values:
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


def normalize_date_to_iso(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("Z", "+00:00")
    try:
        if "T" in raw or "+" in raw:
            dt = datetime.fromisoformat(raw)
            return dt.date().isoformat()
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if match:
        dd, mm, yyyy = match.groups()
        try:
            return date(int(yyyy), int(mm), int(dd)).isoformat()
        except ValueError:
            return ""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if match:
        return match.group(1)
    return ""


def normalize_datetime_to_iso(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("Z", "+00:00")
    try:
        if "T" in raw or "+" in raw:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.isoformat(timespec="seconds")
        d = date.fromisoformat(raw[:10])
        return datetime(d.year, d.month, d.day, 0, 0, 0).isoformat(timespec="seconds")
    except ValueError:
        pass
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if match:
        dd, mm, yyyy = match.groups()
        try:
            return datetime(int(yyyy), int(mm), int(dd), 0, 0, 0).isoformat(timespec="seconds")
        except ValueError:
            return ""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if match:
        return f"{match.group(1)}T00:00:00"
    return ""


def detect_id_type(doc_id: str) -> str:
    value = str(doc_id or "").strip()
    if not value:
        return "unknown"
    if UUID_PATTERN.fullmatch(value):
        return "uuid"
    if value.isdigit():
        return "numeric"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        return "slug"
    return "unknown"


def _normalize_relation_type(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        return RELATION_TYPE_MAP.get(int(value), f"unknown_{int(value)}")
    except (TypeError, ValueError):
        return str(value).strip() or "unknown"


def _summarize_document_issues(issues: Any) -> tuple[list[dict[str, str]], int]:
    summarized: list[dict[str, str]] = []
    total = 0
    if isinstance(issues, list):
        total = len(issues)
        source = issues[:3]
    elif isinstance(issues, dict):
        total = 1
        source = [issues]
    else:
        source = []

    for item in source:
        if not isinstance(item, dict):
            continue
        summarized.append(
            {
                "personName": str(item.get("personName") or "").strip(),
                "jobTitleName": str(item.get("jobTitleName") or "").strip(),
                "agencyName": str(item.get("agencyName") or "").strip(),
            }
        )
    return summarized, total


def _extract_title(soup: BeautifulSoup) -> str:
    candidates: list[str] = []
    for selector in (
        "meta[property='og:title']",
        "meta[name='title']",
        "h1",
        "h2",
        ".title",
        "#title",
        ".toanvan-title",
    ):
        if selector.startswith("meta"):
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                candidates.append(tag.get("content", ""))
        else:
            for tag in soup.select(selector):
                text = tag.get_text(" ", strip=True)
                if text:
                    candidates.append(text)
    return _pick_first(candidates)


def _collect_label_value_pairs(soup: BeautifulSoup) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = cells[0].get_text(" ", strip=True)
        value = cells[1].get_text(" ", strip=True)
        if not key or not value:
            continue
        data.setdefault(_normalize_key(key), []).append(value)

    for item in soup.select("li, p, div, span"):
        text = item.get_text(" ", strip=True)
        if ":" not in text or len(text) > 300:
            continue
        key, value = text.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        data.setdefault(_normalize_key(key), []).append(value)
    return data


def _match_field(label_values: dict[str, list[str]], synonyms: list[str]) -> str:
    for key, values in label_values.items():
        for synonym in synonyms:
            if synonym in key:
                picked = _pick_first(values)
                if picked:
                    return picked
    return ""


def _extract_file_urls(soup: BeautifulSoup, page_url: str) -> list[str]:
    file_urls: list[str] = []
    seen: set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(page_url, href)
        lower = full_url.lower()
        if any(ext in lower for ext in (".pdf", ".doc", ".docx", ".rtf")) or (
            "/filedata/" in lower or "/attachments/" in lower
        ):
            if full_url not in seen:
                seen.add(full_url)
                file_urls.append(full_url)
    return file_urls


def _extract_related_documents(soup: BeautifulSoup, page_url: str) -> list[str]:
    related: list[str] = []
    seen: set[str] = set()
    for section in soup.find_all(["div", "section", "table", "ul"]):
        section_text = _normalize_key(section.get_text(" ", strip=True))
        if not any(
            key in section_text
            for key in (
                "van ban lien quan",
                "van ban huong dan",
                "van ban sua doi",
                "van ban duoc can cu",
                "can cu",
            )
        ):
            continue
        for a_tag in section.find_all("a", href=True):
            full_url = urljoin(page_url, a_tag.get("href", "").strip())
            if "ItemID=" not in full_url:
                continue
            if full_url not in seen:
                seen.add(full_url)
                related.append(full_url)
    return related


def _extract_content_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
        tag.decompose()

    selectors = [
        "#toanvancontent",
        ".toanvancontent",
        "#ctl00_Content_vanBanChiTiet",
        ".content",
        ".vbpq-content",
        "#content",
        "main",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return clean_legal_text(node.get_text("\n", strip=True))
    return clean_legal_text(soup.get_text("\n", strip=True))


def extract_doc_id(source_url: str) -> str:
    url = str(source_url or "").strip()
    if not url:
        return ""
    match = DOC_DETAIL_ID_PATTERN.search(url)
    if match:
        return match.group(1).strip()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("ItemID", "itemid", "id"):
        values = query.get(key) or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    match = UUID_PATTERN.search(url)
    return match.group(0) if match else ""


def _safe_get_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


def _build_legal_structure(content_text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in content_text.splitlines() if line.strip()]
    articles: list[dict[str, Any]] = []
    current_article: dict[str, Any] | None = None
    current_clause: dict[str, Any] | None = None

    for line in lines:
        normalized = _normalize_for_match(line)
        article_match = re.match(r"^dieu\s+(\d+)[\.:]?\s*(.*)$", normalized)
        if article_match:
            title = re.sub(r"^\s*Điều\s+\d+[\.:]?\s*", "", line, flags=re.IGNORECASE).strip()
            current_article = {
                "article_number": article_match.group(1),
                "article_title": title,
                "content": [],
                "clauses": [],
            }
            articles.append(current_article)
            current_clause = None
            continue

        clause_match = CLAUSE_RE.match(line)
        if clause_match and current_article is not None:
            current_clause = {
                "clause_number": clause_match.group(1),
                "content": clause_match.group(2).strip(),
                "points": [],
            }
            current_article["clauses"].append(current_clause)
            continue

        point_match = POINT_RE.match(line)
        if point_match and current_clause is not None:
            current_clause["points"].append(
                {
                    "point_key": point_match.group(1).lower(),
                    "content": point_match.group(2).strip(),
                }
            )
            continue

        if current_clause is not None:
            current_clause["content"] = f"{current_clause['content']} {line}".strip()
        elif current_article is not None:
            current_article["content"].append(line)

    return articles


def _normalize_attachment_type(file_name: str) -> str:
    lower_name = file_name.lower()
    if lower_name.endswith(".pdf"):
        return "pdf"
    if lower_name.endswith(".doc"):
        return "doc"
    if lower_name.endswith(".docx"):
        return "docx"
    if lower_name.endswith(".rtf"):
        return "rtf"
    if lower_name.endswith(".html"):
        return "html"
    if lower_name.endswith(".json"):
        return "json"
    return "other"


def parse_document_detail_from_api(
    doc_id: str,
    detail_data: dict[str, Any],
    file_items: list[dict[str, Any]] | None = None,
    source_url: str = "",
) -> dict[str, Any]:
    issue = detail_data.get("documentIssues")
    signer = ""
    if isinstance(issue, list) and issue:
        signer = str(issue[0].get("personName") or "").strip()
    elif isinstance(issue, dict):
        signer = str(issue.get("personName") or "").strip()
    issue_summary, issue_count = _summarize_document_issues(issue)

    summary = ""
    references = detail_data.get("references")
    if isinstance(references, str):
        summary = references.strip()

    fields = detail_data.get("documentFields") or []
    majors = detail_data.get("documentMajors") or []
    field = ""
    if fields and isinstance(fields, list):
        field = ", ".join(str(item.get("name", "")).strip() for item in fields if item.get("name"))
    if not field and majors and isinstance(majors, list):
        field = ", ".join(str(item.get("name", "")).strip() for item in majors if item.get("name"))

    related_documents: list[dict[str, Any]] = []
    for rel in detail_data.get("documentRelatedList") or []:
        if not isinstance(rel, dict):
            continue
        related_id = ""
        for key in ("relatedDocumentId", "targetDocumentId", "sourceDocumentId", "id"):
            value = str(rel.get(key) or "").strip()
            if value:
                related_id = value
                break
        if related_id:
            related_documents.append(
                {
                    "id": related_id,
                    "url": f"https://vbpl.vn/van-ban/chi-tiet/{related_id}",
                    "relation_type": _normalize_relation_type(rel.get("relatedType")),
                    "title": rel.get("title") or rel.get("relatedTitle") or "",
                }
            )

    file_urls: list[str] = []
    fallback_urls: list[str] = []
    attachments: list[dict[str, Any]] = []
    for file_item in file_items or []:
        if not isinstance(file_item, dict):
            continue
        presigned = str(file_item.get("presignedUrl") or "").strip()
        if not presigned:
            continue
        file_name = str(file_item.get("fileName") or "").strip()
        file_ext_type = _normalize_attachment_type(file_name)
        attachments.append(
            {
                "file_name": file_name,
                "display_name": str(file_item.get("originalFileName") or file_name),
                "file_type": file_ext_type,
                "url": presigned,
            }
        )
        lower_name = file_name.lower()
        if any(lower_name.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".rtf")):
            file_urls.append(presigned)
        else:
            fallback_urls.append(presigned)
    if not file_urls:
        file_urls = fallback_urls

    content_raw = detail_data.get("documentContent")
    content_html = ""
    if isinstance(content_raw, dict):
        content_html = str(content_raw.get("content") or "")
    elif isinstance(content_raw, str):
        content_html = content_raw
    if content_html and "<" in content_html and ">" in content_html:
        soup = BeautifulSoup(content_html, "lxml")
        content_text = clean_legal_text(soup.get_text("\n", strip=True))
    else:
        content_text = clean_legal_text(content_html)
    articles = _build_legal_structure(content_text)
    canonical_doc_id = doc_id or extract_doc_id(source_url)
    source = source_url.strip() or f"https://vbpl.vn/van-ban/chi-tiet/{canonical_doc_id}"

    return {
        "title": str(detail_data.get("title") or "").strip(),
        "document_type": _safe_get_name(detail_data.get("docType")),
        "document_number": str(detail_data.get("docNum") or "").strip(),
        "summary": summary,
        "issuing_agency": str(detail_data.get("agencyName") or "").strip(),
        "signer": signer,
        "issued_date": normalize_date_to_iso(detail_data.get("issueDate")),
        "issued_at": normalize_datetime_to_iso(detail_data.get("issueDate")),
        "effective_date": normalize_date_to_iso(detail_data.get("effFrom")),
        "effective_at": normalize_datetime_to_iso(detail_data.get("effFrom")),
        "expired_date": normalize_date_to_iso(detail_data.get("effTo")),
        "expired_at": normalize_datetime_to_iso(detail_data.get("effTo")),
        "gazette_date": normalize_date_to_iso(detail_data.get("publicDate")),
        "gazette_at": normalize_datetime_to_iso(detail_data.get("publicDate")),
        "updated_date": normalize_date_to_iso(detail_data.get("updatedDate")),
        "updated_at": normalize_datetime_to_iso(detail_data.get("updatedDate")),
        "status": _safe_get_name(detail_data.get("effStatus")),
        "field": field,
        "source_url": source,
        "canonical_doc_id": canonical_doc_id,
        "id_type": detect_id_type(canonical_doc_id),
        "file_urls": file_urls,
        "related_documents": related_documents,
        "attachments": attachments,
        "full_html_content": content_html,
        "articles": articles,
        "content_text": content_text,
        "candidate_fields": {
            "docType": [str(detail_data.get("docType"))[:200]],
            "effStatus": [str(detail_data.get("effStatus"))[:200]],
            "documentIssues_count": [str(issue_count)],
            "documentIssues_summary": issue_summary,
        },
    }


def parse_document_detail(page_url: str, raw_html: str) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html, "lxml")
    label_values = _collect_label_value_pairs(soup)
    candidates = {k: v[:2] for k, v in label_values.items()}

    title = _extract_title(soup)
    document_number = _match_field(label_values, ["so ky hieu", "so hieu", "so van ban", "so"])
    document_type = _match_field(label_values, ["loai van ban", "hinh thuc", "ten loai"])
    summary = _match_field(label_values, ["trich yeu", "noi dung", "ten goi", "tom tat"])
    issuing_agency = _match_field(label_values, ["co quan ban hanh", "co quan"])
    signer = _match_field(label_values, ["nguoi ky", "chuc danh", "ky boi"])
    issued_date = _match_field(label_values, ["ngay ban hanh", "ngay ky"])
    effective_date = _match_field(label_values, ["ngay co hieu luc", "hieu luc tu ngay"])
    expired_date = _match_field(label_values, ["ngay het hieu luc"])
    gazette_date = _match_field(label_values, ["ngay cong bao"])
    status = _match_field(label_values, ["tinh trang hieu luc", "trang thai"])
    field = _match_field(label_values, ["linh vuc", "nganh", "pham vi"])

    page_text = soup.get_text("\n", strip=True)
    if not document_number:
        match = re.search(r"\b\d+/\d{4}/[A-Z0-9\-]+\b", page_text)
        if match:
            document_number = match.group(0)
    if not document_type:
        for token in ("Luat", "Nghi dinh", "Thong tu", "Quyet dinh", "Nghi quyet"):
            if token in _normalize_for_match(page_text):
                document_type = token
                break
    if not title:
        title = summary

    file_urls = _extract_file_urls(soup, page_url)
    related_documents = _extract_related_documents(soup, page_url)
    content_text = _extract_content_text(soup)
    articles = _build_legal_structure(content_text)
    canonical_doc_id = extract_doc_id(page_url)

    return {
        "title": title,
        "document_type": document_type,
        "document_number": document_number,
        "summary": summary,
        "issuing_agency": issuing_agency,
        "signer": signer,
        "issued_date": normalize_date_to_iso(issued_date),
        "effective_date": normalize_date_to_iso(effective_date),
        "expired_date": normalize_date_to_iso(expired_date),
        "gazette_date": normalize_date_to_iso(gazette_date),
        "updated_date": "",
        "updated_at": "",
        "status": status,
        "field": field,
        "source_url": page_url,
        "canonical_doc_id": canonical_doc_id,
        "id_type": detect_id_type(canonical_doc_id),
        "file_urls": file_urls,
        "related_documents": related_documents,
        "attachments": [{"file_name": "", "display_name": "", "file_type": "url", "url": u} for u in file_urls],
        "full_html_content": raw_html,
        "articles": articles,
        "content_text": content_text,
        "candidate_fields": candidates,
    }


def build_document_record(
    page_url: str,
    parsed: dict[str, Any],
    raw_html_path: str,
    downloaded_files: list[str],
) -> dict[str, Any]:
    stable_id = hashlib.sha1(page_url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    crawl_time = datetime.now(timezone.utc).isoformat()
    return {
        "id": stable_id,
        "canonical_doc_id": parsed.get("canonical_doc_id", extract_doc_id(page_url)),
        "id_type": parsed.get("id_type", detect_id_type(parsed.get("canonical_doc_id", ""))),
        "title": parsed.get("title", ""),
        "document_type": parsed.get("document_type", ""),
        "document_number": parsed.get("document_number", ""),
        "summary": parsed.get("summary", ""),
        "issuing_agency": parsed.get("issuing_agency", ""),
        "signer": parsed.get("signer", ""),
        "issued_date": parsed.get("issued_date", ""),
        "issued_at": parsed.get("issued_at", ""),
        "effective_date": parsed.get("effective_date", ""),
        "effective_at": parsed.get("effective_at", ""),
        "expired_date": parsed.get("expired_date", ""),
        "expired_at": parsed.get("expired_at", ""),
        "gazette_date": parsed.get("gazette_date", ""),
        "gazette_at": parsed.get("gazette_at", ""),
        "updated_date": parsed.get("updated_date", ""),
        "updated_at": parsed.get("updated_at", ""),
        "status": parsed.get("status", ""),
        "field": parsed.get("field", ""),
        "source_url": parsed.get("source_url", page_url),
        "file_urls": parsed.get("file_urls", []),
        "related_documents": parsed.get("related_documents", []),
        "attachments": parsed.get("attachments", []),
        "topic_labels": parsed.get("topic_labels", []),
        "topic_names": parsed.get("topic_names", []),
        "matched_keywords": parsed.get("matched_keywords", []),
        "matched_fields": parsed.get("matched_fields", {}),
        "raw_html_path": raw_html_path,
        "downloaded_files": downloaded_files,
        "full_html_content": parsed.get("full_html_content", ""),
        "articles": parsed.get("articles", []),
        "content_text": parsed.get("content_text", ""),
        "crawl_time": crawl_time,
    }

