"""
scanner/larajobs.py
-------------------
LaraJobs public RSS feed (no auth): https://larajobs.com/feed

RSS 2.0 <item> fields used: title, link (or guid), pubDate, dc:creator,
larajobs:company, larajobs:location, and content:encoded/description (HTML).
Namespace-agnostic: tags are matched by their local name. Field names verified
against the live feed (Oct 2026).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.larajobs")

FEED_URL = "https://larajobs.com/feed"
_ACCEPT = "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"


def _item_fields(item: ET.Element) -> dict[str, str]:
    """Map an RSS item's direct children by local tag name (namespace-agnostic)."""
    fields: dict[str, str] = {}
    for child in item:
        name = child.tag.rsplit("}", 1)[-1]
        text = (child.text or "").strip()
        if text and name not in fields:
            fields[name] = text
    return fields


@register("larajobs")
class LaraJobsScanner(BaseScanner):
    name = "larajobs"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(FEED_URL, timeout=self.timeout, accept=_ACCEPT)
        root = ET.fromstring(resp.content)
        jobs: list[NormalizedJob] = []
        for item in root.iter("item"):
            fields = _item_fields(item)
            title = fields.get("title", "")
            url = fields.get("link") or fields.get("guid") or ""
            description = clean_html(fields.get("encoded") or fields.get("description") or "")
            jobs.append(NormalizedJob(
                title=title,
                company=fields.get("company") or fields.get("creator") or "",
                location=fields.get("location") or "Remote",
                description=description,
                url=url,
                source="larajobs",
                posted_at=fields.get("pubDate", ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("LaraJobs: fetched %d jobs", len(jobs))
        return jobs
