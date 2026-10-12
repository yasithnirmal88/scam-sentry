"""
scanner/himalayas.py
--------------------
Himalayas public jobs API (no auth): https://himalayas.app/jobs/api

Response: {"jobs": [{title, companyName, locationRestrictions[],
description (HTML), applicationLink, guid, pubDate (epoch seconds),
employmentType, ...}], ...}. Field names verified against the live API
(Oct 2026).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.himalayas")

API_URL = "https://himalayas.app/jobs/api"


@register("himalayas")
class HimalayasScanner(BaseScanner):
    name = "himalayas"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(API_URL, params={"limit": max(1, min(limit, 100))},
                        timeout=self.timeout)
        payload = resp.json()
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            restrictions = item.get("locationRestrictions")
            if isinstance(restrictions, list):
                location = ", ".join(str(x) for x in restrictions if x)
            else:
                location = str(restrictions or "")
            posted_at = ""
            pub = item.get("pubDate")
            if isinstance(pub, (int, float)):
                try:
                    posted_at = datetime.fromtimestamp(
                        int(pub), tz=timezone.utc).isoformat()
                except (ValueError, TypeError, OSError):
                    posted_at = ""
            jobs.append(NormalizedJob(
                title=str(item.get("title") or "").strip(),
                company=str(item.get("companyName") or "").strip(),
                location=location or "Remote",
                description=clean_html(item.get("description") or ""),
                url=str(item.get("applicationLink") or item.get("guid") or "").strip(),
                source="himalayas",
                posted_at=posted_at or str(pub or ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("Himalayas: fetched %d jobs", len(jobs))
        return jobs
