"""Tests for the SQLite jobs store."""

from models.job import JobRecord, count_jobs, get_job, init_db, list_jobs, risk_counts, save_job


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


def test_save_get_list_filter(tmp_path):
    db = str(tmp_path / "t.db")
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


def test_upsert_same_url(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    a = save_job(_sample(), db)
    rec = _sample()
    rec.overall_risk_level = "High"
    b = save_job(rec, db)
    assert a == b
    assert count_jobs(db_path=db) == 1
    assert get_job(a, db)["overall_risk_level"] == "High"


def test_risk_counts(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    save_job(_sample("https://example.com/1"), db)
    rec = _sample("https://example.com/2")
    rec.overall_risk_level = "Critical"
    save_job(rec, db)
    counts = risk_counts(db)
    assert counts["Low"] == 1 and counts["Critical"] == 1 and counts["total"] == 2


def test_get_missing(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert get_job(999, db) is None
