"""Tests for Phase 2 dashboard pages (server-rendered, no network)."""

import pytest

import config
from models.job import JobRecord, init_db, save_job


@pytest.fixture()
def page_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "dash.db"))
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
        url="https://example.com/qa-dash", source="remoteok",
        overall_risk_level="Medium", risk_categories=["Suspicious"],
        confidence="Medium", key_indicators=[{
            "id": "M1", "name": "Vague role description", "severity": "Medium",
            "category": "Suspicious", "evidence": "...", "explanation": "Why."}],
        recommended_actions=["Verify the employer."],
        employer_verification={"company_website": "Found", "email_domain_match": "N/A",
                               "role_on_careers_page": "Unknown", "notes": "n"},
        summary="Some suspicious characteristics were found.",
        hybrid_score=0.4, rule_score=0.3, ml_score=0.5))


def test_dashboard_home_renders(page_client):
    res = page_client.get("/dashboard")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Job Risk Dashboard" in html
    for level in ("Critical", "High", "Medium", "Low"):
        assert level in html
    assert "Run New Scan" in html
    assert "dashboard.js" in html


def test_dashboard_home_shows_counts(page_client):
    _seed()
    html = page_client.get("/dashboard").get_data(as_text=True)
    assert "QA Engineer" not in html  # cards render client-side via API
    assert 'id="count-medium">1<' in html


def test_job_detail_renders_report(page_client):
    jid = _seed()
    res = page_client.get(f"/dashboard/jobs/{jid}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "QA Engineer" in html
    assert "MEDIUM" in html
    assert "Vague role description" in html
    assert "M1" in html
    assert "Verify the employer." in html
    assert "https://example.com/qa-dash" in html
    assert "Back to Dashboard" in html


def test_job_detail_404(page_client):
    res = page_client.get("/dashboard/jobs/9999")
    assert res.status_code == 404
    assert "Back to Dashboard" in res.get_data(as_text=True)


def test_index_links_dashboard(page_client):
    html = page_client.get("/").get_data(as_text=True)
    assert "/dashboard" in html
