from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .enterprise_taxonomy import match_keywords
from .http_client import HttpClient

DOC_PATH_PATTERN = re.compile(r"/Pages/vbpq-(van-ban-goc|toanvan)\.aspx", re.IGNORECASE)
API_DOC_ALL = "https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/all"


def _normalize_date_only(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return ""


def _normalize_datetime(value: str) -> datetime | None:
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
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _is_vbpl_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("vbpl.vn")


def _normalize_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href.strip())


def extract_document_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not href:
            continue
        full_url = _normalize_url(base_url, href)
        if not _is_vbpl_url(full_url):
            continue
        if not DOC_PATH_PATTERN.search(full_url):
            continue
        if "ItemID=" not in full_url:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)
    return urls


def discover_document_urls(
    client: HttpClient,
    list_page_urls: list[str],
    raw_list_pages_dir: Path,
    max_documents: int = 10,
) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    raw_list_pages_dir.mkdir(parents=True, exist_ok=True)

    for idx, list_url in enumerate(list_page_urls, start=1):
        try:
            html = client.fetch_html(list_url)
        except Exception as exc:  # noqa: BLE001
            client.logger.exception("Failed to fetch list page %s: %s", list_url, exc)
            continue

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        file_name = raw_list_pages_dir / f"list_page_{idx}_{ts}.html"
        file_name.write_text(html, encoding="utf-8")
        client.logger.info("Saved raw list page: %s", file_name)

        urls = extract_document_urls(html=html, base_url=list_url)
        client.logger.info("Found %s candidate document URLs from %s", len(urls), list_url)
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            discovered.append(url)
            if len(discovered) >= max_documents:
                return discovered
    return discovered


def _api_item_match_fields(item: dict) -> dict[str, object]:
    return {
        "title": item.get("title", ""),
        "document_number": item.get("docNum", ""),
        "document_type": item.get("docType"),
        "field": item.get("documentFields") or item.get("documentMajors"),
        "status": item.get("effStatus"),
        "agency": item.get("agencyName", ""),
    }


def discover_document_urls_from_api(
    client: HttpClient,
    raw_list_pages_dir: Path,
    max_documents: int = 10,
    since_date: str = "",
    skip_doc_ids: set[str] | None = None,
    include_title_keywords: list[str] | None = None,
) -> list[str]:
    raw_list_pages_dir.mkdir(parents=True, exist_ok=True)
    page_number = 1
    page_size = min(max(max_documents, 5), 50)
    discovered: list[str] = []
    seen_ids: set[str] = set()
    skip_ids = skip_doc_ids or set()
    keyword_filter = [keyword for keyword in (include_title_keywords or []) if str(keyword or "").strip()]
    skipped_existing = 0
    skipped_by_keyword = 0
    normalized_since_dt = _normalize_datetime(since_date)

    while len(discovered) < max_documents:
        payload = {
            "pageNumber": page_number,
            "pageSize": page_size,
            "sortBy": "issueDate",
            "sortDirection": "desc",
        }
        response = client.post_json(API_DOC_ALL, payload=payload)

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        raw_file = raw_list_pages_dir / f"list_api_page_{page_number}_{ts}.json"
        raw_file.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        client.logger.info("Saved API list page: %s", raw_file)

        data = response.get("data") or {}
        items = data.get("items") or []
        if not items:
            break
        all_old_in_page = True

        for item in items:
            doc_id = str(item.get("id", "")).strip()
            if not doc_id or doc_id in seen_ids:
                continue
            item_dt = _normalize_datetime(str(item.get("updatedDate") or item.get("issueDate") or ""))
            if normalized_since_dt:
                if item_dt and item_dt < normalized_since_dt:
                    continue
                all_old_in_page = False
            if doc_id in skip_ids:
                skipped_existing += 1
                continue
            if keyword_filter:
                keyword_match = match_keywords(_api_item_match_fields(item), keyword_filter)
                if not keyword_match["is_match"]:
                    skipped_by_keyword += 1
                    continue
            if not normalized_since_dt:
                all_old_in_page = False
            seen_ids.add(doc_id)
            discovered.append(f"https://vbpl.vn/van-ban/chi-tiet/{doc_id}")
            if len(discovered) >= max_documents:
                break

        if normalized_since_dt and all_old_in_page:
            break

        total = int(data.get("total") or 0)
        if page_number * page_size >= total:
            break
        page_number += 1
    if skip_ids:
        client.logger.info("Skipped %s doc IDs already present in local index during list discovery", skipped_existing)
    if keyword_filter:
        client.logger.info("Skipped %s list items not matching list metadata keywords", skipped_by_keyword)
    return discovered
