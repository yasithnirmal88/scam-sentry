"""Phase 5 (Dashboard UX): scan history API + template surfaces.

Covers: ``list_scan_history`` on both backends (newest first, tolerant of a
missing table), the ``/api/scan/history`` endpoint, and the ML-honesty +
accessibility markup the dashboard now renders.
"""

import pytest

import config
from models.job import init_db, list_scan_history, record_scan_run


@pytest.fixture()
def history_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "ue.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        yield client


def _run():
    return {
        "started_at": "2026-01-01T10:00:00+00:00",
        "finished_at": "2026-01-01T10:05:00+00:00",
        "sources": {"remotive": 3, "remoteok": 2},
        "fetched": 5, "evaluated": 5, "stored": 4,
        "skipped": 0, "duplicates": 1, "status": "partial",
        "errors": {"remoteok": "2/3 failed"},
    }


def test_scan_history_roundtrip_newest_first(db):
    init_db(db)
    assert list_scan_history(db) == []
    record_scan_run(_run(), db_path=db)
    record_scan_run({**_run(), "started_at": "2026-01-02T00:00:00+00:00"}, db_path=db)
    runs = list_scan_history(db)
    assert len(runs) == 2
    assert runs[0]["started_at"] == "2026-01-02T00:00:00+00:00"
    assert runs[0]["status"] == "partial"
    assert runs[0]["sources"] == ["remotive", "remoteok"]
    assert runs[0]["stored"] == 4
    assert runs[0]["duplicates"] == 1


def test_scan_history_limited_and_tolerant(db, tmp_path):
    init_db(db)
    for _ in range(25):
        record_scan_run(_run(), db_path=db)
    assert len(list_scan_history(db)) == 20
    assert len(list_scan_history(limit=5, db_path=db)) == 5
    # A bogus locator must degrade to an empty list, never raise.
    assert list_scan_history(db_path=str(tmp_path / "missing.db")) == []


def test_dashboard_has_cv_matcher_panel(history_client):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    js = (root / "static" / "cv_matcher.js").read_text(encoding="utf-8")
    assert 'id="cv-matcher"' in html
    assert 'id="cv-file"' in html and 'id="btn-match"' in html
    assert 'id="cv-hide-risky"' in html
    assert "/api/match/cv" in js
    page = history_client.get("/dashboard")
    assert page.status_code == 200
    assert b"Match Jobs to Your CV" in page.data


def test_dashboard_cards_link_to_original_posting(history_client):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    # Card source is a real link to the original posting, opening a new tab.
    assert "job-source-link" in js
    assert 'target="_blank"' in js
    assert 'rel="noopener noreferrer"' in js
    assert "job.url" in js
    detail = (root / "templates" / "job_detail.html").read_text(encoding="utf-8")
    assert "job.url" in detail
    assert 'target="_blank"' in detail
    assert 'rel="noopener noreferrer"' in detail


def test_api_scan_history(history_client):
    res = history_client.get("/api/scan/history")
    assert res.status_code == 200
    assert res.get_json() == {"runs": []}

    from models.job import record_scan_run as record

    record(_run())
    body = history_client.get("/api/scan/history?limit=5").get_json()
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["status"] == "partial"
    assert run["stored"] == 4


def test_api_scan_history_after_a_scan_run(history_client):
    from services.scanner_service import run_scan
    from services import scheduler

    run_scan(sources=["remoteok"], limit_per_source=1)
    runs = history_client.get("/api/scan/history").get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] in ("success", "partial", "empty", "failed")
    assert runs[0]["stored"] >= 0
    assert scheduler.get_status()["running"] is False


def test_scan_history_surfaces_empty_status(history_client):
    record_scan_run({
        "started_at": "2026-03-01T00:00:00+00:00",
        "finished_at": "2026-03-01T00:00:10+00:00",
        "sources": {"remoteok": 0}, "fetched": 0, "evaluated": 0,
        "stored": 0, "skipped": 0, "duplicates": 0,
        "status": "empty", "errors": {},
    })
    runs = history_client.get("/api/scan/history").get_json()["runs"]
    assert runs[0]["status"] == "empty"
    assert runs[0]["stored"] == 0


def test_dashboard_maps_empty_status_to_a_chip():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    css = (root / "static" / "style.css").read_text(encoding="utf-8")
    assert "status-empty" in js
    assert ".status-empty" in css


def test_dashboard_uses_filtered_and_global_totals():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    html = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    # The global "Total Jobs Stored" card reads global_total; the filtered
    # matching count is surfaced separately via #filter-summary.
    assert "data.global_total" in js
    assert "data.total" in js
    assert 'id="filter-summary"' in html


def test_dashboard_pages_carry_phase5_markup(history_client):
    dash = history_client.get("/dashboard").get_data(as_text=True)
    assert "Recent Scan Runs" in dash
    assert "scan-runs" in dash
    assert 'aria-live="polite"' in dash
    assert 'aria-pressed="true"' in dash
    # No token entry UI on the dashboard: scans run without a token by design.
    assert "scan-token-input" not in dash
    assert "X-Scan-Token" not in dash
    # Industry + job-role search sections for targeted applications.
    assert "Search by Industry" in dash
    assert 'id="filter-industry"' in dash
    assert 'id="filter-role"' in dash

    home = history_client.get("/").get_data(as_text=True)
    assert "How the ML probability is derived" in home
    assert 'id="ml-note-text"' in home


def test_dashboard_has_country_region_controls(history_client):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    assert "Search by Country / Region" in html
    assert 'id="filter-country"' in html
    assert 'id="filter-region"' in html
    assert 'id="filter-remote"' in html
    # Filtering happens server-side via the query string.
    assert 'params.set("country"' in js
    assert 'params.set("region"' in js
    assert 'params.set("remote"' in js
    assert "populateLocationOptions" in js
    # And the rendered page carries the controls.
    dash = history_client.get("/dashboard").get_data(as_text=True)
    assert 'id="filter-country"' in dash
    assert 'id="filter-region"' in dash
    assert 'id="filter-remote"' in dash


def test_dashboard_scan_flow_needs_no_token_when_anonymous_enabled(
        history_client, monkeypatch):
    """Local dev/demo: with SCAN_ALLOW_ANONYMOUS=true and no token, the
    dashboard-style trigger (no X-Scan-Token header) is authorized."""
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", True)
    res = history_client.post(
        "/api/scan", json={"sources": ["bogus"]})
    assert res.status_code == 400  # authorized: reached source validation


def test_dashboard_scan_flow_fail_closed_by_default(history_client, monkeypatch):
    """Default hardening: no token + anonymous off => dashboard trigger 401s."""
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", False)
    res = history_client.post("/api/scan", json={"sources": ["bogus"]})
    assert res.status_code == 401


def test_job_detail_carries_ml_honesty_note(history_client):
    from models.job import JobRecord, save_job

    save_job(JobRecord(
        url="https://example.com/ux-1", title="Support Engineer",
        overall_risk_level="Low", hybrid_score=0.2,
        rule_score=0.1, ml_score=0.3))
    html = history_client.get(
        "/dashboard/jobs/1").get_data(as_text=True)
    assert "synthetic-trained" in html
    assert "deterministic Risk Engine" in html


def test_job_detail_shows_industry_role_chips(history_client):
    from models.job import JobRecord, save_job

    save_job(JobRecord(
        url="https://example.com/ux-2", title="Senior Software Engineer",
        overall_risk_level="Low", industry="Technology & IT",
        job_role="Software Engineer"))
    html = history_client.get(
        "/dashboard/jobs/1").get_data(as_text=True)
    assert "Industry: Technology &amp; IT" in html or "Technology & IT" in html
    assert "Role: Software Engineer" in html