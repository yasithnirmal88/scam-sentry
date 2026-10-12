"""
scanner/workingnomads.py
------------------------
Working Nomads public jobs feed (no auth):
  https://www.workingnomads.com/api/exposed_jobs/

Response: a JSON **list** of postings:
  [{url, title, description (HTML), company_name, category_name, tags[],
    location, pub_date}, ...]

This endpoint is public and key-free but can be slow, so the scanner keeps a
per-source timeout floor (config.WORKINGNOMADS_TIMEOUT) above the shared
default. Field names verified against the live API (Oct 2026).
"""

from __future__ import annotations

import logging

import config

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.workingnomads")

API_URL = "https://www.workingnomads.com/api/exposed_jobs/"


@register("workingnomads")
class WorkingNomadsScanner(BaseScanner):
    name = "workingnomads"

    def __init__(self, timeout: int | None = None) -> None:
        super().__init__(timeout)
        # Working Nomads often responds slowly; never time out below the floor.
        self.timeout = max(self.timeout, config.WORKINGNOMADS_TIMEOUT)

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(API_URL, timeout=self.timeout)
        payload = resp.json()
        items = payload if isinstance(payload, list) else payload.get("jobs", [])
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            location = str(item.get("location") or "").strip()
            if not location:
                location = str(item.get("category_name") or "").strip() or "Remote"
            jobs.append(NormalizedJob(
                title=str(item.get("title") or "").strip(),
                company=str(item.get("company_name") or "").strip(),
                location=location,
                description=clean_html(item.get("description") or ""),
                url=str(item.get("url") or "").strip(),
                source="workingnomads",
                posted_at=str(item.get("pub_date") or ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("Working Nomads: fetched %d jobs", len(jobs))
        return jobs
