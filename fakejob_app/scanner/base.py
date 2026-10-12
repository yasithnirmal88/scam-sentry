"""
scanner/base.py
---------------
Contracts for public job-source scanners.

Every scanner returns NormalizedJob dicts:
  title, company, location, description, url, source, posted_at
"""

from __future__ import annotations

import html
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

import config

logger = logging.getLogger("scam_sentry.scanner")

_TAG_RE = re.compile(r"<[^>]+>")

# Tracking params that create distinct URLs for the same posting.
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "fbclid", "gclid", "ref", "source"}


def http_get(url: str, params: dict | None = None,
             timeout: int | None = None,
             accept: str = "application/json") -> requests.Response:
    """GET with retries + shared User-Agent. Raises the last error if all fail.

    `accept` overrides the Accept header for non-JSON sources (e.g. RSS/XML);
    the default preserves the previous JSON-only behaviour.
    """
    attempts = max(1, config.SCANNER_RETRIES + 1)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": config.SCANNER_USER_AGENT,
                         "Accept": accept},
                timeout=timeout or config.SCANNER_TIMEOUT,
            )
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            logger.warning("GET %s attempt %d/%d failed: %s", url, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(config.SCANNER_RETRY_BACKOFF * attempt)
    assert last_exc is not None
    raise last_exc


_ALLOWED_SCHEMES = {"http", "https"}


def normalize_url(url: str | None) -> str:
    """Canonicalize a posting URL so re-scans dedupe reliably.

    Only http(s) URLs are accepted; anything else (javascript:, data:, ...)
    returns "" so it is dropped rather than rendered as a link.
    """
    if not url:
        return ""
    raw = url.strip()
    try:
        parts = urlparse(raw)
    except Exception:
        return ""
    scheme = (parts.scheme or "").lower()
    if scheme and scheme not in _ALLOWED_SCHEMES:
        return ""
    if not scheme:
        if not parts.netloc:
            return ""
        scheme = "https"
    host = (parts.netloc or "").lower()
    path = parts.path.rstrip("/") or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in _TRACKING_PARAMS]
    return urlunparse((scheme, host, path, "", urlencode(query), ""))


def clean_html(raw: str | None) -> str:
    """Strip HTML tags/entities to plain text for the Risk Engine."""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


@dataclass
class NormalizedJob:
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    source: str = ""
    posted_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def risk_text(self) -> str:
        """Combined text fed to the existing Risk Engine."""
        parts = [self.title, self.company, self.location, self.description]
        return "\n".join(p for p in parts if p)


class BaseScanner(ABC):
    """One public source. Subclass and implement fetch()."""

    name: str = "base"

    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout or config.SCANNER_TIMEOUT

    @abstractmethod
    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        """Return up to `limit` normalized jobs. Raise on fatal errors."""

    def safe_fetch(self, limit: int = 20) -> list[NormalizedJob]:
        try:
            jobs = self.fetch(limit) or []
        except Exception as exc:  # never let one source kill a whole scan
            logger.warning("Scanner %s failed: %s", self.name, exc)
            return []
        # Drop entries with no usable content; cap to limit.
        usable = [j for j in jobs if (j.description or j.title) and j.url]
        return usable[: max(1, limit)]


# Registry — new sources self-register via decorator.
SCANNERS: dict[str, Callable[[], BaseScanner]] = {}


def iter_boards(tokens: list[str], fetch_board: Callable[[str], list["NormalizedJob"]],
                limit: int, max_boards: int) -> list["NormalizedJob"]:
    """Collect jobs across company-board tokens with per-board isolation.

    `fetch_board(token)` returns normalized jobs for one board. A failure on a
    single board is logged and skipped so the rest of the boards still return.
    """
    collected: list[NormalizedJob] = []
    for token in tokens[: max(1, max_boards)]:
        if len(collected) >= limit:
            break
        try:
            collected.extend(fetch_board(token) or [])
        except Exception as exc:  # one bad board must not kill the scanner
            logger.warning("Board %r failed: %s", token, exc)
    return collected[: max(1, limit)]


def register(name: str) -> Callable[[type[BaseScanner]], type[BaseScanner]]:
    def deco(cls: type[BaseScanner]) -> type[BaseScanner]:
        SCANNERS[name] = cls
        return cls
    return deco


def get_scanner(name: str, **kwargs: Any) -> BaseScanner:
    try:
        factory = SCANNERS[name]
    except KeyError:
        raise ValueError(f"Unknown scanner source: {name!r}. Available: {sorted(SCANNERS)}")
    return factory(**kwargs)


def list_sources() -> list[str]:
    return sorted(SCANNERS)
