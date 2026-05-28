from .clean_text import clean_legal_text
from .discover_urls import discover_document_urls, discover_document_urls_from_api
from .download_files import download_attachments
from .http_client import HttpClient
from .parse_detail import (
    build_document_record,
    extract_doc_id,
    parse_document_detail,
    parse_document_detail_from_api,
)
from .save_jsonl import append_full_and_rag, append_jsonl, build_rag_ready_record

__all__ = [
    "HttpClient",
    "discover_document_urls",
    "discover_document_urls_from_api",
    "parse_document_detail",
    "parse_document_detail_from_api",
    "build_document_record",
    "extract_doc_id",
    "download_attachments",
    "clean_legal_text",
    "append_jsonl",
    "append_full_and_rag",
    "build_rag_ready_record",
]
