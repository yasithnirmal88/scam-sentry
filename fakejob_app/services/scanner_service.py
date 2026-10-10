"""
services/scanner_service.py
---------------------------
Orchestrates: fetch from sources -> evaluate with Risk Engine -> store.
Dedupes by URL within a run and relies on UNIQUE(url) upserts in storage.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import config
from models.job import JobRecord, init_db, save_job
from scanner import get_scanner, list_sources
from services.evaluation_service import evaluate_job

logger = logging.getLogger("scam_sentry.scanner_service")


def run_scan(sources: Optional[list[str]] = None, limit_per_source: int | None = None,
             db_path: Optional[str] = None) -> dict[str, Any]:
    """Run one scan cycle. Returns a summary dict (never raises on source errors)."""
    init_db(db_path)
    wanted = sources or list_sources()
    per_source = max(1, min(int(limit_per_source or config.SCANNER_DEFAULT_LIMIT), 100))

    summary: dict[str, Any] = {
        "sources": {}, "fetched": 0, "evaluated": 0, "stored": 0, "errors": {},
    }
    seen_urls: set[str] = set()

    for name in wanted:
        try:
            scanner = get_scanner(name)
        except ValueError as exc:
            summary["errors"][name] = str(exc)
            continue
        jobs = scanner.safe_fetch(per_source)
        summary["sources"][name] = len(jobs)
        summary["fetched"] += len(jobs)

        for job in jobs:
            if not job.url or job.url in seen_urls:
                continue
            seen_urls.add(job.url)
            try:
                risk = evaluate_job(job.title, job.company, job.location, job.description)
            except ValueError as exc:  # too short / unusable text
                logger.info("Skipping %s: %s", job.url, exc)
                continue
            except Exception as exc:
                logger.warning("Evaluation failed for %s: %s", job.url, exc)
                summary["errors"].setdefault("evaluation", []).append(job.url)
                continue
            record = JobRecord(
                title=job.title, company=job.company, location=job.location,
                description=job.description, raw_description=job.description,
                url=job.url, source=job.source, posted_at=job.posted_at,
                overall_risk_level=risk.get("overall_risk_level", "Low"),
                risk_categories=risk.get("risk_categories", []),
                confidence=risk.get("confidence", "Low"),
                key_indicators=risk.get("key_indicators", []),
                recommended_actions=risk.get("recommended_actions", []),
                employer_verification=risk.get("employer_verification", {}),
                summary=risk.get("summary", ""),
                hybrid_score=float(risk.get("hybrid_score", 0.0) or 0.0),
                rule_score=float(risk.get("rule_score", 0.0) or 0.0),
                ml_score=float(risk.get("ml_score", 0.0) or 0.0),
            )
            save_job(record, db_path)
            summary["evaluated"] += 1
            summary["stored"] += 1

    logger.info("Scan complete: %s", {k: v for k, v in summary.items() if k != "sources"})
    return summary
