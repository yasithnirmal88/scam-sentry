"""
scanner/jobicy.py
-----------------
Jobicy public remote-jobs API (no auth):
  https://jobicy.com/api/v2/remote-jobs?count=N

Response: {"jobCount": N, "jobs": [{id, url, jobTitle, companyName,
jobType[], jobLevel, jobLocation/jobGeo, jobIndustry[], jobDescription (HTML),
jobExcerpt, salaryMin/Max/Currency/Period, pubDate}], ...}
Field names verified against the live API (Oct 2026).
"""

from __future__ import annotations

import logging

from .base import BaseScanner, NormalizedJob, clean_html, http_get, register

logger = logging.getLogger("scam_sentry.scanner.jobicy")

API_URL = "https://jobicy.com/api/v2/remote-jobs"


@register("jobicy")
class JobicyScanner(BaseScanner):
    name = "jobicy"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        resp = http_get(API_URL, params={"count": max(1, min(limit, 50))},
                        timeout=self.timeout)
        payload = resp.json()
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs: list[NormalizedJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            description = clean_html(item.get("jobDescription") or item.get("jobExcerpt") or "")
            location = (str(item.get("jobLocation") or "").strip()
                        or str(item.get("jobGeo") or "").strip() or "Remote")
            jobs.append(NormalizedJob(
                title=str(item.get("jobTitle") or item.get("title") or "").strip(),
                company=str(item.get("companyName") or item.get("company") or "").strip(),
                location=location,
                description=description,
                url=str(item.get("url") or "").strip(),
                source="jobicy",
                posted_at=str(item.get("pubDate") or item.get("publication_date") or ""),
            ))
            if len(jobs) >= limit:
                break
        logger.info("Jobicy: fetched %d jobs", len(jobs))
        return jobs
