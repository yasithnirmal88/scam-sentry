"""
scanner/remotive.py
-------------------
Remotive public API (no auth): https://remotive.com/api/remote-jobs
Response shape: {"jobs": [{title, company_name, candidate_required_location,
description, url, publication_date, ...}]}.
"""

from __future__ import annotations

import logging

import requests

import config
from .base import BaseScanner, NormalizedJob, clean_html, register

logger = logging.getLogger("scam_sentry.scanner.remotive")

API_URL = "https://remotive.com/api/remote-jobs"


@register("remotive")
class RemotiveScanner(BaseScanner):
    name = "remotive"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = requests.get(
            API_URL,
            params={"limit": max(1, min(limit, 100))},
            headers={"User-Agent": config.SCANNER_USER_AGENT, "Accept": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            jobs.append(NormalizedJob(
                title=str(item.get("title") or "").strip(),
                company=str(item.get("company_name") or "").strip(),
                location=str(item.get("candidate_required_location") or "Remote").strip(),
                description=clean_html(item.get("description") or ""),
                url=str(item.get("url") or "").strip(),
                source="remotive",
                posted_at=str(item.get("publication_date") or ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("Remotive: fetched %d jobs", len(jobs))
        return jobs
