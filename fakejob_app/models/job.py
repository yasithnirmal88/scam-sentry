"""
models/job.py
-------------
Persistence for scanned job listings + their risk reports.

This module is the public facade. It selects a storage backend per call
(see ``models/storage.py``):

- explicit ``db_path`` wins (a ``postgres://`` URL selects Postgres),
- else ``config.DATABASE_URL`` (Render / Neon / Supabase Postgres),
- else the local SQLite file ``config.DATABASE_PATH``.

The public API is unchanged: ``init_db``, ``save_job``, ``get_job``,
``list_jobs``, ``count_jobs``, ``risk_counts``, ``record_scan_run``,
``get_last_scan``, ``list_scan_history``, ``utcnow_iso`` and the
``JobRecord`` dataclass.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import location
from models.storage import select_backend

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utcnow_iso() -> str:
    """Current UTC time as ISO string (public alias for services)."""
    return _now_iso()


@dataclass
class JobRecord:
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    raw_description: str = ""
    url: str = ""
    source: str = ""
    posted_at: str = ""
    overall_risk_level: str = "Low"
    risk_categories: list = field(default_factory=list)
    confidence: str = "Low"
    key_indicators: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    employer_verification: dict = field(default_factory=dict)
    summary: str = ""
    hybrid_score: float = 0.0
    rule_score: float = 0.0
    ml_score: float = 0.0
    industry: str = "Other"
    job_role: str = "Other"
    country: str = ""
    region: str = ""
    scanned_at: str = ""


def _job_payload(record: JobRecord) -> dict[str, Any]:
    # Best-effort country/region normalization at write time so every stored
    # row (new scans included) is filterable, regardless of caller. Explicit
    # values win; otherwise infer from the free-text location.
    country = (record.country or "").strip()
    region = (record.region or "").strip()
    if not country:
        country, inferred_region = location.normalize_location(record.location)
        region = region or inferred_region
    return {
        "title": record.title or "",
        "company": record.company or "",
        "location": record.location or "",
        "description": record.description or "",
        "raw_description": record.raw_description or record.description or "",
        "url": record.url or "",
        "source": record.source or "",
        "posted_at": record.posted_at or "",
        "overall_risk_level": record.overall_risk_level or "Low",
        "risk_categories": json.dumps(record.risk_categories or []),
        "confidence": record.confidence or "Low",
        "key_indicators": json.dumps(record.key_indicators or []),
        "recommended_actions": json.dumps(record.recommended_actions or []),
        "employer_verification": json.dumps(record.employer_verification or {}),
        "summary": record.summary or "",
        "hybrid_score": float(record.hybrid_score or 0.0),
        "rule_score": float(record.rule_score or 0.0),
        "ml_score": float(record.ml_score or 0.0),
        "industry": record.industry or "Other",
        "job_role": record.job_role or "Other",
        "country": country,
        "region": region,
        "scanned_at": record.scanned_at or _now_iso(),
    }


def init_db(db_path: Optional[str] = None) -> str:
    """Create tables/indexes if missing. Returns the locator used."""
    with _lock:
        return select_backend(db_path).init()


def save_job(record: JobRecord | dict, db_path: Optional[str] = None) -> int:
    """Insert or update by URL. Returns the row id."""
    if isinstance(record, dict):
        record = JobRecord(
            **{k: v for k, v in record.items() if k in JobRecord.__dataclass_fields__})
    payload = _job_payload(record)
    with _lock:
        return select_backend(db_path).save_job(payload)


def get_job(job_id: int, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with _lock:
        return select_backend(db_path).get_job(job_id)


def list_jobs(risk_level: Optional[str] = None, source: Optional[str] = None,
              query: Optional[str] = None, limit: int = 50, offset: int = 0,
              industry: Optional[str] = None, role: Optional[str] = None,
              country: Optional[str] = None, region: Optional[str] = None,
              remote: Optional[bool] = None,
              db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with _lock:
        return select_backend(db_path).list_jobs(
            risk_level, source, query, limit, offset, industry, role,
            country, region, remote)


def count_jobs(risk_level: Optional[str] = None, source: Optional[str] = None,
               query: Optional[str] = None, industry: Optional[str] = None,
               role: Optional[str] = None, country: Optional[str] = None,
               region: Optional[str] = None, remote: Optional[bool] = None,
               db_path: Optional[str] = None) -> int:
    """Count stored jobs matching the given filters (all optional)."""
    with _lock:
        return select_backend(db_path).count_jobs(
            risk_level, source, query, industry, role, country, region, remote)


def list_all_jobs(limit: int = 2000, db_path: Optional[str] = None,
                  risk_level: Optional[str] = None, source: Optional[str] = None,
                  industry: Optional[str] = None, role: Optional[str] = None,
                  country: Optional[str] = None, region: Optional[str] = None,
                  remote: Optional[bool] = None) -> list[dict[str, Any]]:
    """Up to ``limit`` stored jobs (bounded), for CV matching candidates."""
    with _lock:
        return select_backend(db_path).list_all_jobs(
            limit=limit, risk_level=risk_level, source=source, industry=industry,
            role=role, country=country, region=region, remote=remote)


def location_options(db_path: Optional[str] = None) -> dict[str, list[str]]:
    """Distinct countries/regions present in the store (for the pickers)."""
    with _lock:
        return select_backend(db_path).location_options()


def risk_counts(db_path: Optional[str] = None) -> dict[str, int]:
    with _lock:
        return select_backend(db_path).risk_counts()


def record_scan_run(summary: dict[str, Any], db_path: Optional[str] = None) -> int:
    """Persist one scan run. Returns the history row id (0 on failure)."""
    try:
        payload = {
            "started_at": str(summary.get("started_at") or ""),
            "finished_at": str(summary.get("finished_at") or _now_iso()),
            "sources": json.dumps(list((summary.get("sources") or {}).keys())),
            "fetched": int(summary.get("fetched") or 0),
            "evaluated": int(summary.get("evaluated") or 0),
            "stored": int(summary.get("stored") or 0),
            "skipped": int(summary.get("skipped") or 0),
            "duplicates": int(summary.get("duplicates") or 0),
            "status": str(summary.get("status") or "unknown"),
            "errors": json.dumps(summary.get("errors") or {}),
        }
    except Exception:
        return 0
    try:
        with _lock:
            return select_backend(db_path).record_scan_run(payload)
    except Exception:
        return 0


def get_last_scan(db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Most recent scan run, or None if no scan has been recorded yet."""
    with _lock:
        return select_backend(db_path).get_last_scan()


def list_scan_history(db_path: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent scan runs, newest first (empty list on any error)."""
    with _lock:
        return select_backend(db_path).list_scan_history(limit)
