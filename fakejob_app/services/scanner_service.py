"""
services/scanner_service.py
---------------------------
Orchestrates: fetch from sources -> evaluate with Risk Engine -> store.

- One failing source never stops the whole scan (per-source isolation).
- Dedupes by normalized URL within a run and via UNIQUE(url) upserts.
- Records every run in scan_history with a success/partial/failed status.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import config
from models.job import JobRecord, init_db, record_scan_run, save_job, utcnow_iso
from scanner import get_scanner, list_sources, normalize_url
from services.evaluation_service import evaluate_job

logger = logging.getLogger("scam_sentry.scanner_service")


def _final_status(summary: dict[str, Any]) -> str:
    errors = summary.get("errors") or {}
    if summary.get("stored", 0) > 0:
        return "partial" if errors else "success"
    if summary.get("fetched", 0) > 0:
        return "partial"
    return "failed" if errors else "success"


def run_scan(sources: Optional[list[str]] = None, limit_per_source: int | None = None,
             db_path: Optional[str] = None) -> dict[str, Any]:
    """Run one scan cycle. Returns a summary dict (never raises on source errors)."""
    init_db(db_path)
    wanted = sources or list_sources()
    per_source = max(1, min(int(limit_per_source or config.SCANNER_DEFAULT_LIMIT), 100))

    summary: dict[str, Any] = {
        "started_at": utcnow_iso(), "finished_at": "",
        "sources": {}, "fetched": 0, "evaluated": 0, "stored": 0,
        "skipped": 0, "duplicates": 0, "errors": {}, "status": "unknown",
    }
    seen_urls: set[str] = set()
    logger.info("Scan starting: sources=%s limit_per_source=%d", wanted, per_source)

    for name in wanted:
        started = time.monotonic()
        try:
            scanner = get_scanner(name)
        except ValueError as exc:
            summary["errors"][name] = str(exc)
            continue
        jobs = scanner.safe_fetch(per_source)
        elapsed = time.monotonic() - started
        summary["sources"][name] = len(jobs)
        summary["fetched"] += len(jobs)
        logger.info("Source %s: %d jobs in %.1fs", name, len(jobs), elapsed)
        if not jobs and name not in summary["errors"]:
            summary["errors"][name] = "no jobs returned"

        for job in jobs:
            url = normalize_url(job.url)
            if not url or url in seen_urls:
                summary["duplicates"] += 1
                continue
            seen_urls.add(url)
            job.url = url  # store the canonical form
            try:
                risk = evaluate_job(job.title, job.company, job.location,
                                    job.description, posted_at=job.posted_at)
            except ValueError as exc:  # too short / unusable text
                logger.info("Skipping %s: %s", url, exc)
                summary["skipped"] += 1
                continue
            except Exception as exc:
                logger.warning("Evaluation failed for %s: %s", url, exc)
                summary["skipped"] += 1
                summary["errors"].setdefault("evaluation", []).append(url)
                continue
            record = JobRecord(
                title=job.title, company=job.company, location=job.location,
                description=job.description, raw_description=job.description,
                url=url, source=job.source, posted_at=job.posted_at,
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

    summary["finished_at"] = utcnow_iso()
    summary["status"] = _final_status(summary)
    record_scan_run(summary, db_path)
    logger.info("Scan finished: status=%s fetched=%d stored=%d skipped=%d duplicates=%d errors=%s",
                summary["status"], summary["fetched"], summary["stored"],
                summary["skipped"], summary["duplicates"],
                list(summary["errors"].keys()) or "none")
    return summary
