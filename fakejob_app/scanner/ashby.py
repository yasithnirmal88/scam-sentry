"""
scanner/ashby.py
----------------
Ashby public company job boards (no auth):
  https://api.ashbyhq.com/posting-api/job-board/{board}

Response: {"jobs": [{id, title, location, employmentType, isRemote,
publishedAt, jobUrl, applyUrl, descriptionHtml, descriptionPlain}, ...],
"apiVersion": "..."}

Ashby has no global feed, so the scanner walks config.ASHBY_BOARDS. The board
token is used as the company label. Field names verified against the live API
(Oct 2026).
"""

from __future__ import annotations

import logging

import config

from .base import BaseScanner, NormalizedJob, clean_html, http_get, iter_boards, register

logger = logging.getLogger("scam_sentry.scanner.ashby")

BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"


@register("ashby")
class AshbyScanner(BaseScanner):
    name = "ashby"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        def one_board(board: str) -> list[NormalizedJob]:
            resp = http_get(BOARD_URL.format(board=board), timeout=self.timeout)
            payload = resp.json()
            items = payload.get("jobs", []) if isinstance(payload, dict) else []
            out: list[NormalizedJob] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                location = str(item.get("location") or "").strip()
                if item.get("isRemote") and "remote" not in location.lower():
                    location = (location + " (Remote)").strip()
                out.append(NormalizedJob(
                    title=str(item.get("title") or "").strip(),
                    company=board,
                    location=location or "Remote",
                    description=clean_html(item.get("descriptionPlain")
                                           or item.get("descriptionHtml") or ""),
                    url=str(item.get("jobUrl") or item.get("applyUrl") or "").strip(),
                    source="ashby",
                    posted_at=str(item.get("publishedAt") or ""),
                ))
            return out

        jobs = iter_boards(config.ASHBY_BOARDS, one_board, limit,
                           config.SCANNER_MAX_BOARDS)
        logger.info("Ashby: fetched %d jobs across %d boards",
                    len(jobs), len(config.ASHBY_BOARDS))
        return jobs
