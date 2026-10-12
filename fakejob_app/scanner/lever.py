"""
scanner/lever.py
----------------
Lever public company boards (no auth):
  https://api.lever.co/v0/postings/{board}?mode=json

Response: a JSON list of postings:
  [{id, text (title), categories {location, team, commitment, allLocations[]},
    description / descriptionPlain, hostedUrl, createdAt (epoch ms),
    workplaceType, country}, ...]

Lever has no global feed, so the scanner walks config.LEVER_BOARDS. The board
token is used as the company label (Lever postings omit the company name).
Field names verified against the live API (Oct 2026).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config

from .base import BaseScanner, NormalizedJob, clean_html, http_get, iter_boards, register

logger = logging.getLogger("scam_sentry.scanner.lever")

BOARD_URL = "https://api.lever.co/v0/postings/{board}"


@register("lever")
class LeverScanner(BaseScanner):
    name = "lever"

    def fetch(self, limit: int = 20) -> list[NormalizedJob]:
        def one_board(board: str) -> list[NormalizedJob]:
            resp = http_get(BOARD_URL.format(board=board),
                            params={"mode": "json"}, timeout=self.timeout)
            payload = resp.json()
            items = payload if isinstance(payload, list) else []
            out: list[NormalizedJob] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                cats = item.get("categories") or {}
                location = str(cats.get("location") or "").strip()
                if not location and isinstance(cats.get("allLocations"), list):
                    location = ", ".join(str(x) for x in cats["allLocations"] if x)
                posted_at = ""
                created = item.get("createdAt")
                if isinstance(created, (int, float)):
                    try:
                        posted_at = datetime.fromtimestamp(
                            created / 1000, tz=timezone.utc).isoformat()
                    except (ValueError, TypeError, OSError):
                        posted_at = ""
                out.append(NormalizedJob(
                    title=str(item.get("text") or "").strip(),
                    company=board,
                    location=location or "Unknown",
                    description=clean_html(item.get("descriptionPlain")
                                           or item.get("description") or ""),
                    url=str(item.get("hostedUrl") or "").strip(),
                    source="lever",
                    posted_at=posted_at,
                ))
            return out

        jobs = iter_boards(config.LEVER_BOARDS, one_board, limit,
                           config.SCANNER_MAX_BOARDS)
        logger.info("Lever: fetched %d jobs across %d boards",
                    len(jobs), len(config.LEVER_BOARDS))
        return jobs
