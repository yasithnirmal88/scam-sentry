"""Tests for /api/jobs, /api/jobs/<id>, /api/scan (no network)."""

import pytest

import config
from models.job import JobRecord, init_db, save_job
from scanner.base import NormalizedJob


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "test-token")
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        yield client


def _seed():
    return save_job(JobRecord(
        title="QA Engineer", company="Acme", location="Remote",
        description="Test software. Requirements: pytest experience.",
        url="https://example.com/qa", source="remoteok",
        overall_risk_level="Medium", risk_categories=["Suspicious"],
        confidence="Medium"))


def test_list_jobs_empty(api_client):
    res = api_client.get("/api/jobs")
    assert res.status_code == 200
    body = res.get_json()
    assert body["jobs"] == [] and body["total"] == 0


def test_list_filter_and_detail(api_client):
    jid = _seed()
    assert api_client.get("/api/jobs").get_json()["total"] == 1
    assert api_client.get("/api/jobs?risk_level=Medium").get_json()["jobs"][0]["id"] == jid
    assert api_client.get("/api/jobs?risk_level=Critical").get_json()["jobs"] == []
    detail = api_client.get(f"/api/jobs/{jid}")
    assert detail.status_code == 200
    assert detail.get_json()["title"] == "QA Engineer"
    assert api_client.get("/api/jobs/9999").status_code == 404


def test_trigger_scan_stores_with_risk(api_client, monkeypatch):
    import services.scanner_service as svc

    fake_jobs = [NormalizedJob(
        title="Data Entry", company="X", location="Remote",
        description="Pay a refundable registration fee now. Apply immediately!",
        url="https://example.com/scam1", source="remoteok", posted_at="2026-01-01")]

    class FakeScanner:
        name = "remoteok"

        def safe_fetch(self, limit=20):
            return fake_jobs

    monkeypatch.setattr(svc, "get_scanner", lambda name, **k: FakeScanner())
    res = api_client.post("/api/scan?sync=1",
                          json={"sources": ["remoteok"], "limit": 5},
                          headers={"X-Scan-Token": "test-token"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["stored"] == 1 and body["sources"] == {"remoteok": 1}
    jobs = api_client.get("/api/jobs").get_json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["overall_risk_level"] == "Critical"
    assert any(k["id"] == "C1" for k in jobs[0]["key_indicators"])


def test_trigger_scan_unknown_source(api_client):
    res = api_client.post("/api/scan", json={"sources": ["linkedin"], "limit": 5},
                          headers={"X-Scan-Token": "test-token"})
    assert res.status_code == 400


def test_single_job_analysis_still_works(api_client):
    res = api_client.post("/api/analyze/text", json={
        "text": "Senior Engineer at Acme Corp, Remote. Build APIs. Requirements: 3 years Python. "
                "Salary 100000 USD. Apply via official portal."})
    assert res.status_code == 200
    assert res.get_json()["overall_risk_level"] in ("Low", "Medium", "High", "Critical")
