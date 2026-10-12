"""
scanner/greenhouse.py
---------------------
Greenhouse public company job boards (no auth), one request per board:
  https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

Response: {"jobs": [{title, company_name, absolute_url,
location: {name}, content (HTML-escaped), first_published, updated_at, ...}]}.
There is no global endpoint, so config.GREENHOUSE_BOARDS lists the public
board tokens walked each scan. Field names verified against the live API
(Oct 2026).
"""

from __future__ import annotations

import html
import logging

import config

from .base import (BaseScanner, NormalizedJob, clean_html, http_get,
                   iter_boards, register)

logger = logging.getLogger("scam_sentry.scanner.greenhouse")

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


@register("greenhouse")
class GreenhouseScanner(BaseScanner):
    name = "greenhouse"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        def one_board(board: str) -> list[NormalizedJob]:
            resp = http_get(BOARD_URL.format(board=board),
                            params={"content": "true"}, timeout=self.timeout)
            payload = resp.json()
            items = payload.get("jobs", []) if isinstance(payload, dict) else []
            out: list[NormalizedJob] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Greenhouse returns HTML-escaped markup in `content`.
                description = clean_html(html.unescape(item.get("content") or ""))
                loc = item.get("location")
                location = loc.get("name") if isinstance(loc, dict) else str(loc or "")
                out.append(NormalizedJob(
                    title=str(item.get("title") or "").strip(),
                    company=str(item.get("company_name") or board).strip(),
                    location=location or "Unknown",
                    description=description,
                    url=str(item.get("absolute_url") or "").strip(),
                    source="greenhouse",
                    posted_at=str(item.get("first_published")
                                  or item.get("updated_at") or ""),
                ))
            return out

        jobs = iter_boards(config.GREENHOUSE_BOARDS, one_board, limit,
                           config.SCANNER_MAX_BOARDS)
        logger.info("Greenhouse: fetched %d jobs across %d boards",
                    len(jobs), len(config.GREENHOUSE_BOARDS))
        return jobs
