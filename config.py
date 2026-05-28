from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://vbpl.vn"
    api_base_url: str = "https://vbpl-bientap-gateway.moj.gov.vn/api"
    user_agent: str = "vbpl-crawler/0.1 (+contact: local-dev)"
    timeout_seconds: int = 20
    retry_total: int = 3
    retry_backoff_factor: float = 1.2
    request_delay_seconds: float = 1.0
    max_sample_docs: int = 10


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(
    os.getenv("VBPL_DATA_DIR", str(PROJECT_ROOT / "data"))
).expanduser().resolve()
RAW_DIR = DATA_DIR / "raw"
RAW_HTML_DIR = RAW_DIR / "html"
RAW_LIST_PAGES_DIR = RAW_DIR / "list_pages"
RAW_FILES_DIR = RAW_DIR / "files"
PROCESSED_DIR = DATA_DIR / "processed"
LOG_DIR = DATA_DIR / "logs"
JSONL_OUTPUT = PROCESSED_DIR / "legal_documents.jsonl"
FULL_JSONL_OUTPUT = PROCESSED_DIR / "legal_documents_full.jsonl"
RAG_READY_JSONL_OUTPUT = PROCESSED_DIR / "legal_documents_rag_ready.jsonl"
LOG_FILE = LOG_DIR / "crawler.log"

DEFAULT_LIST_URLS = [
    "https://vbpl.vn/van-ban/trung-uong",
    "https://vbpl.vn/van-ban/dia-phuong",
]


def ensure_data_dirs() -> None:
    for path in (
        RAW_HTML_DIR,
        RAW_LIST_PAGES_DIR,
        RAW_FILES_DIR,
        PROCESSED_DIR,
        LOG_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    ensure_data_dirs()
    logger = logging.getLogger("vbpl_crawler")
    logger.setLevel(level)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
