"""
models/job.py
-------------
SQLite persistence for scanned job listings + their risk reports.

Single stdlib dependency (sqlite3). JSON columns store lists/dicts.
`url` is UNIQUE so re-scans upsert instead of duplicating.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    raw_description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    overall_risk_level TEXT NOT NULL DEFAULT 'Low',
    risk_categories TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'Low',
    key_indicators TEXT NOT NULL DEFAULT '[]',
    recommended_actions TEXT NOT NULL DEFAULT '[]',
    employer_verification TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    hybrid_score REAL NOT NULL DEFAULT 0.0,
    rule_score REAL NOT NULL DEFAULT 0.0,
    ml_score REAL NOT NULL DEFAULT 0.0,
    scanned_at TEXT NOT NULL DEFAULT '',
    UNIQUE(url)
);
CREATE INDEX IF NOT EXISTS idx_jobs_risk ON jobs(overall_risk_level);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
"""


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or config.DATABASE_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> str:
    """Create tables/indexes if missing. Returns the db path used."""
    path = db_path or config.DATABASE_PATH
    with _lock, _connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    scanned_at: str = ""


def save_job(record: JobRecord | dict, db_path: Optional[str] = None) -> int:
    """Insert or update by URL. Returns the row id."""
    if isinstance(record, dict):
        record = JobRecord(**{k: v for k, v in record.items() if k in JobRecord.__dataclass_fields__})
    if not record.scanned_at:
        record.scanned_at = _now_iso()
    payload = {
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
        "scanned_at": record.scanned_at,
    }
    cols = ", ".join(payload.keys())
    placeholders = ", ".join(":" + k for k in payload.keys())
    # Update risk fields + scanned_at on conflict; keep original posting fields.
    updates = ", ".join(
        f"{c}=excluded.{c}" for c in (
            "title", "company", "location", "description", "raw_description",
            "source", "posted_at", "overall_risk_level", "risk_categories",
            "confidence", "key_indicators", "recommended_actions",
            "employer_verification", "summary", "hybrid_score",
            "rule_score", "ml_score", "scanned_at",
        )
    )
    with _lock, _connect(db_path) as conn:
        cur = conn.execute(
            f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(url) DO UPDATE SET {updates}",
            payload,
        )
        conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = conn.execute("SELECT id FROM jobs WHERE url = ?", (payload["url"],)).fetchone()
        return int(row["id"]) if row else 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for col in ("risk_categories", "key_indicators", "recommended_actions"):
        try:
            d[col] = json.loads(d.get(col) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[col] = []
    try:
        d["employer_verification"] = json.loads(d.get("employer_verification") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["employer_verification"] = {}
    return d


def get_job(job_id: int, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with _lock, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(risk_level: Optional[str] = None, source: Optional[str] = None,
              query: Optional[str] = None, limit: int = 50, offset: int = 0,
              db_path: Optional[str] = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if risk_level:
        clauses.append("overall_risk_level = ?")
        params.append(risk_level.capitalize() if risk_level.lower() in
                      ("low", "medium", "high", "critical") else risk_level)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if query:
        clauses.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    with _lock, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY scanned_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_jobs(risk_level: Optional[str] = None, db_path: Optional[str] = None) -> int:
    with _lock, _connect(db_path) as conn:
        if risk_level:
            row = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE overall_risk_level = ?",
                               (risk_level,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
    return int(row["n"]) if row else 0


def risk_counts(db_path: Optional[str] = None) -> dict[str, int]:
    with _lock, _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT overall_risk_level, COUNT(*) AS n FROM jobs GROUP BY overall_risk_level"
        ).fetchall()
    out = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    for r in rows:
        out[str(r["overall_risk_level"])] = int(r["n"])
    out["total"] = sum(out.values())
    return out
