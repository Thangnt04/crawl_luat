from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass(frozen=True)
class HttpClientConfig:
    user_agent: str
    timeout_seconds: int = 20
    retry_total: int = 3
    retry_backoff_factor: float = 1.2
    request_delay_seconds: float = 1.0


class HttpClient:
    def __init__(self, config: HttpClientConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
            }
        )
        retry = Retry(
            total=config.retry_total,
            backoff_factor=config.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._last_request_ts = 0.0

    def _sleep_if_needed(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait_for = self.config.request_delay_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    def _origin(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_robot_parser(self, url: str) -> RobotFileParser:
        origin = self._origin(url)
        if origin in self._robots_cache:
            return self._robots_cache[origin]
        rp = RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            rp.read()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Cannot read robots.txt for %s: %s", origin, exc)
        self._robots_cache[origin] = rp
        return rp

    def is_allowed(self, url: str) -> bool:
        rp = self._get_robot_parser(url)
        try:
            allowed = rp.can_fetch(self.config.user_agent, url)
            if not allowed:
                self.logger.warning("Blocked by robots.txt: %s", url)
            return allowed
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("robots check failed, continue with caution: %s", exc)
            return True

    def fetch_html(self, url: str) -> str:
        if not self.is_allowed(url):
            raise PermissionError(f"robots.txt disallows URL: {url}")
        self._sleep_if_needed()
        self.logger.info("GET %s", url)
        response = self.session.get(url, timeout=self.config.timeout_seconds)
        self._last_request_ts = time.monotonic()
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def fetch_binary(self, url: str) -> bytes:
        if not self.is_allowed(url):
            raise PermissionError(f"robots.txt disallows URL: {url}")
        self._sleep_if_needed()
        self.logger.info("GET(binary) %s", url)
        response = self.session.get(url, timeout=self.config.timeout_seconds)
        self._last_request_ts = time.monotonic()
        response.raise_for_status()
        return response.content

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_allowed(url):
            raise PermissionError(f"robots.txt disallows URL: {url}")
        self._sleep_if_needed()
        self.logger.info("POST %s", url)
        response = self.session.post(
            url,
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        self._last_request_ts = time.monotonic()
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.json()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_allowed(url):
            raise PermissionError(f"robots.txt disallows URL: {url}")
        self._sleep_if_needed()
        self.logger.info("GET(json) %s", url)
        response = self.session.get(
            url,
            params=params,
            timeout=self.config.timeout_seconds,
        )
        self._last_request_ts = time.monotonic()
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.json()
