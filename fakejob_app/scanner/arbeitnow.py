"""
scanner/arbeitnow.py
--------------------
Arbeitnow public job board API (no auth):
  https://arbeitnow.com/api/job-board-api

Response: {"data": [{slug, company_name, title, description (HTML),
url, location, remote, job_types, tags, created_at (epoch str)}], ...}
Field names verified against the live API (Oct 2026).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.arbeitnow")

API_URL = "https://arbeitnow.com/api/job-board-api"


@register("arbeitnow")
class ArbeitnowScanner(BaseScanner):
    name = "arbeitnow"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(API_URL, timeout=self.timeout)
        payload = resp.json()
        items = payload.get("data", []) if isinstance(payload, dict) else []
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url and item.get("slug"):
                url = "https://www.arbeitnow.com/jobs/%s" % item["slug"]
            posted_at = ""
            created = item.get("created_at")
            if created:
                try:
                    posted_at = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
                except (ValueError, TypeError, OSError):
                    posted_at = str(created)
            location = str(item.get("location") or "").strip()
            if not location and item.get("remote") in (True, "True", "true"):
                location = "Remote"
            jobs.append(NormalizedJob(
                title=str(item.get("title") or "").strip(),
                company=str(item.get("company_name") or "").strip(),
                location=location or "Unknown",
                description=clean_html(item.get("description") or ""),
                url=url,
                source="arbeitnow",
                posted_at=posted_at,
            ))
            if len(jobs) >= limit:
                break
        logger.info("Arbeitnow: fetched %d jobs", len(jobs))
        return jobs
