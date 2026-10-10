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
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Callable

import config

logger = logging.getLogger("scam_sentry.scanner")

_TAG_RE = re.compile(r"<[^>]+>")


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
