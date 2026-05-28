from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from .http_client import HttpClient


def _safe_filename(url: str) -> str:
    parsed = urlparse(url)
    basename = Path(parsed.path).name or "attachment.bin"
    digest = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"{digest}_{basename}"


def download_attachments(
    client: HttpClient,
    file_urls: list[str],
    output_dir: Path,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    for file_url in file_urls:
        try:
            content = client.fetch_binary(file_url)
        except Exception as exc:  # noqa: BLE001
            client.logger.warning("Failed to download file %s: %s", file_url, exc)
            continue
        filename = _safe_filename(file_url)
        destination = output_dir / filename
        destination.write_bytes(content)
        downloaded.append(str(destination))
        client.logger.info("Downloaded file %s -> %s", file_url, destination)
    return downloaded

