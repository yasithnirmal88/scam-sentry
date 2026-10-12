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
from models.storage import SQLiteBackend, select_backend


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


def test_industry_role_roundtrip_and_filter(db):
    init_db(db)
    tech = _sample("https://example.com/tech")
    tech.industry, tech.job_role = ("Technology & IT", "Software Engineer")
    health = _sample("https://example.com/health")
    health.title = "Registered Nurse"
    health.industry, health.job_role = ("Healthcare", "Registered Nurse")
    heatlh_id = save_job(health, db)
    tech_id = save_job(tech, db)
    assert heatlh_id > 0 and tech_id > 0

    got = get_job(tech_id, db)
    assert got["industry"] == "Technology & IT"
    assert got["job_role"] == "Software Engineer"

    rows = list_jobs(industry="Healthcare", db_path=db)
    assert [r["id"] for r in rows] == [heatlh_id]
    rows = list_jobs(industry="Healthcare", role="Registered Nurse", db_path=db)
    assert [r["id"] for r in rows] == [heatlh_id]
    rows = list_jobs(industry="Healthcare", role="Software Engineer", db_path=db)
    assert rows == []
    rows = list_jobs(industry="Technology & IT", role="Software Engineer", db_path=db)
    assert [r["id"] for r in rows] == [tech_id]
    rows = list_jobs(role="Registered Nurse", db_path=db)
    assert [r["id"] for r in rows] == [heatlh_id]


def test_default_industry_role_is_other(db):
    init_db(db)
    jid = save_job(_sample("https://example.com/plain"), db)
    job = get_job(jid, db)
    assert job["industry"] == "Other"
    assert job["job_role"] == "Other"


def test_sqlite_migrates_old_schema_in_place(tmp_path):
    """A jobs table created before the industry/role feature is lifted to
    the current schema on init_db, keeping existing rows ("Other")."""
    path = str(tmp_path / "legacy.db")
    legacy = """
    CREATE TABLE jobs (
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
    CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '',
        sources TEXT NOT NULL DEFAULT '[]',
        fetched INTEGER NOT NULL DEFAULT 0,
        evaluated INTEGER NOT NULL DEFAULT 0,
        stored INTEGER NOT NULL DEFAULT 0,
        skipped INTEGER NOT NULL DEFAULT 0,
        duplicates INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'unknown',
        errors TEXT NOT NULL DEFAULT '{}'
    );
    """
    backend = SQLiteBackend(path)
    with backend._connect() as conn:  # noqa: SLF001 (test uses legacy API)
        conn.executescript(legacy)
        conn.execute(
            "INSERT INTO jobs (title, url) VALUES ('Legacy Job', "
            "'https://example.com/legacy')")
        conn.commit()

    init_db(path)
    job = get_job(1, path)
    assert job["title"] == "Legacy Job"
    assert job["industry"] == "Other"
    assert job["job_role"] == "Other"
    # Migration is idempotent.
    init_db(path)