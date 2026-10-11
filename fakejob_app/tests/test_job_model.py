"""Tests for the jobs store, parameterized over SQLite and Postgres.

The ``db`` fixture (tests/conftest.py) runs each test once per backend:
- sqlite  -> a unique temp file
- postgres -> a real PostgreSQL database (only when TEST_POSTGRES_URL is set)
"""

"""Tests for the jobs store, parameterized over SQLite and Postgres.

The ``db`` fixture (tests/conftest.py) runs each test once per backend:
- sqlite     -> a unique temp file
- postgres   -> a real PostgreSQL database (only when TEST_POSTGRES_URL is set)
"""

from models.job import (
    JobRecord, count_jobs, get_job, get_last_scan, init_db, list_jobs,
    record_scan_run, risk_counts, save_job,
)
from models.storage import select_backend


def _sample(url="https://example.com/jobs/1"):
    return JobRecord(
        title="Support Engineer", company="Acme", location="Remote",
        description="Help customers via email. Requirements: 2 years experience.",
        url=url, source="remoteok", posted_at="2026-01-01",
        overall_risk_level="Low", risk_categories=["Likely Genuine"],
        confidence="Medium", key_indicators=[], recommended_actions=["a"],
        employer_verification={"company_website": "Found"},
        summary="Looks fine.", hybrid_score=0.1, rule_score=0.0, ml_score=0.2,
    )


def test_save_get_list_filter(db):
    init_db(db)
    jid = save_job(_sample(), db)
    assert jid > 0
    job = get_job(jid, db)
    assert job["title"] == "Support Engineer"
    assert job["risk_categories"] == ["Likely Genuine"]
    assert job["employer_verification"] == {"company_website": "Found"}
    assert list_jobs(db_path=db)[0]["id"] == jid
    assert list_jobs(risk_level="Low", db_path=db)
    assert list_jobs(risk_level="Critical", db_path=db) == []
    assert count_jobs(db_path=db) == 1


def test_upsert_same_url(db):
    init_db(db)
    a = save_job(_sample(), db)
    rec = _sample()
    rec.overall_risk_level = "High"
    b = save_job(rec, db)
    assert a == b
    assert count_jobs(db_path=db) == 1
    assert get_job(a, db)["overall_risk_level"] == "High"


def test_risk_counts(db):
    init_db(db)
    save_job(_sample("https://example.com/1"), db)
    rec = _sample("https://example.com/2")
    rec.overall_risk_level = "Critical"
    save_job(rec, db)
    counts = risk_counts(db)
    assert counts["Low"] == 1 and counts["Critical"] == 1 and counts["total"] == 2


def test_get_missing(db):
    init_db(db)
    assert get_job(999, db) is None


def test_query_limit_offset(db):
    init_db(db)
    for i in range(5):
        save_job(_sample(f"https://example.com/jobs/{i}"), db)
    rows = list_jobs(query="support", limit=2, offset=0, db_path=db)
    assert len(rows) == 2
    rows2 = list_jobs(query="support", limit=2, offset=2, db_path=db)
    assert len(rows2) == 2
    assert {r["id"] for r in rows}.isdisjoint({r["id"] for r in rows2})


def test_scan_history_roundtrip(db):
    init_db(db)
    hid = record_scan_run({
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "sources": {"remoteok": 5}, "fetched": 5, "evaluated": 4, "stored": 4,
        "skipped": 1, "duplicates": 0, "status": "partial",
        "errors": {"remoteok": "no jobs"},
    }, db)
    assert hid > 0
    last = get_last_scan(db)
    assert last is not None
    assert last["status"] == "partial"
    assert last["stored"] == 4
    assert last["sources"] == ["remoteok"]
    assert last["errors"] == {"remoteok": "no jobs"}


def test_backend_selection(monkeypatch):
    monkeypatch.setattr("config.DATABASE_PATH", "/tmp/x.db")
    monkeypatch.setattr("config.DATABASE_URL", "")
    assert type(select_backend(None)).__name__ == "SQLiteBackend"
    monkeypatch.setattr("config.DATABASE_URL", "postgresql://u:p@h/db")
    assert type(select_backend(None)).__name__ == "PostgresBackend"
    # explicit db_path wins over DATABASE_URL
    assert type(select_backend("/etc/x.db")).__name__ == "SQLiteBackend"
    # a postgres URL passed as db_path selects Postgres
    monkeypatch.setattr("config.DATABASE_URL", "")
    assert type(
        select_backend("postgresql://u:p@h/db")).__name__ == "PostgresBackend"


def test_get_last_scan_empty(db):
    init_db(db)
    assert get_last_scan(db) is None