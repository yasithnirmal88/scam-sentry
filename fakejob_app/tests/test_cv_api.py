"""Tests for POST /api/match/cv (upload + validation + response shape)."""

import io

import pytest

import config
from models.job import JobRecord, init_db, save_job

CV_TEXT = ("Senior Backend Software Engineer\n"
           "Skills: Python, Django, PostgreSQL, Docker, AWS\n"
           "Built REST APIs and data pipelines with Python.\n")


@pytest.fixture()
def cv_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "cv.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        yield client


def _seed_jobs():
    good = save_job(JobRecord(
        title="Python Backend Engineer", company="Acme",
        location="Berlin, Germany",
        description="Python, Django, PostgreSQL, Docker and AWS. REST APIs.",
        url="https://example.com/good", source="remoteok",
        overall_risk_level="Low", industry="Technology & IT",
        job_role="Software Engineer"))
    bad = save_job(JobRecord(
        title="Python Backend Engineer (urgent)", company="QuickCash",
        description="Python Django. Pay a registration fee to start.",
        url="https://example.com/bad", source="remoteok",
        overall_risk_level="Critical", industry="Technology & IT",
        job_role="Software Engineer"))
    return good, bad


def test_match_cv_with_pasted_text(cv_client):
    good, bad = _seed_jobs()
    res = cv_client.post("/api/match/cv", json={"cv_text": CV_TEXT})
    assert res.status_code == 200
    body = res.get_json()
    assert "cv" in body and "matches" in body
    assert body["candidate_jobs"] == 2
    assert body["cv"]["tools"]  # python etc. detected
    assert body["cv"]["summary"]
    assert body["disclaimer"]
    ids = [m["job_id"] for m in body["matches"]]
    # Safe job ranks first; the critical one is pushed to the bottom.
    assert ids[0] == good
    assert ids[-1] == bad
    top = body["matches"][0]
    assert top["risk_level"] == "Low"
    assert top["fit_score"] > 0
    assert "python" in top["matched_terms"]


def test_match_cv_upload_txt_file(cv_client):
    _seed_jobs()
    data = {"file": (io.BytesIO(CV_TEXT.encode("utf-8")), "cv.txt")}
    res = cv_client.post("/api/match/cv", data=data,
                         content_type="multipart/form-data")
    assert res.status_code == 200
    assert res.get_json()["cv"]["extraction"] == "text"


def test_match_cv_exclude_risky_filter(cv_client):
    good, bad = _seed_jobs()
    body = cv_client.post(
        "/api/match/cv",
        data={"cv_text": CV_TEXT, "exclude_risky": "1"},
        content_type="multipart/form-data").get_json()
    ids = [m["job_id"] for m in body["matches"]]
    assert good in ids and bad not in ids
    assert body["filters"]["exclude_risky"] is True


def test_match_cv_min_fit_filter(cv_client):
    _seed_jobs()
    body = cv_client.post("/api/match/cv",
                          json={"cv_text": CV_TEXT, "min_fit": 90}).get_json()
    assert all(m["fit_score"] >= 90 for m in body["matches"])


def test_match_cv_rejects_unsupported_extension(cv_client):
    data = {"file": (io.BytesIO(b"legacy"), "cv.doc")}
    res = cv_client.post("/api/match/cv", data=data,
                         content_type="multipart/form-data")
    assert res.status_code == 400
    assert "PDF, TXT, or DOCX" in res.get_json()["error"]


def test_match_cv_rejects_too_little_text(cv_client):
    res = cv_client.post("/api/match/cv", json={"cv_text": "hi"})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_match_cv_rejects_missing_body(cv_client):
    res = cv_client.post("/api/match/cv")
    assert res.status_code == 400


def test_match_cv_empty_database_returns_no_matches(cv_client):
    res = cv_client.post("/api/match/cv", json={"cv_text": CV_TEXT})
    assert res.status_code == 200
    body = res.get_json()
    assert body["matches"] == []
    assert body["candidate_jobs"] == 0
