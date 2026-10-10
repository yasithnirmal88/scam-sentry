"""
scanner/remoteok.py
-------------------
RemoteOK public API (no auth): https://remoteok.com/api
Returns a JSON list; first element is legal metadata, rest are postings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.remoteok")

API_URL = "https://remoteok.com/api"


@register("remoteok")
class RemoteOKScanner(BaseScanner):
    name = "remoteok"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(API_URL, timeout=self.timeout)
        items = resp.json()
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict) or "position" not in item:
                continue  # skip the leading legal/metadata element
            description = clean_html(item.get("description") or "")
            posted_at = ""
            epoch = item.get("epoch")
            if epoch:
                try:
                    posted_at = datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
                except (ValueError, TypeError, OSError):
                    posted_at = ""
            jobs.append(NormalizedJob(
                title=str(item.get("position") or "").strip(),
                company=str(item.get("company") or "").strip(),
                location=str(item.get("location") or "Remote").strip(),
                description=description,
                url=str(item.get("url") or "").strip(),
                source="remoteok",
                posted_at=posted_at or str(item.get("date") or ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("RemoteOK: fetched %d jobs", len(jobs))
        return jobs
