"""Tests for Phase 4 polish: headers, limits, welcome state, deploy files."""

import io
import os

import pytest

import config
from models.job import init_db


@pytest.fixture()
def web_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "polish.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        yield client


def test_security_headers(web_client):
    res = web_client.get("/api/health")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "Referrer-Policy" in res.headers
    csp = res.headers.get("Content-Security-Policy")
    assert csp and "default-src 'self'" in csp
    assert "script-src 'self'" in csp and "frame-ancestors 'self'" in csp


def test_upload_too_large_returns_json(web_client):
    import app as app_module
    old = app_module.app.config["MAX_CONTENT_LENGTH"]
    app_module.app.config["MAX_CONTENT_LENGTH"] = 10
    try:
        res = web_client.post(
            "/api/analyze/file",
            data={"file": (io.BytesIO(b"x" * 100), "job.pdf")},
            content_type="multipart/form-data",
        )
    finally:
        app_module.app.config["MAX_CONTENT_LENGTH"] = old
    assert res.status_code == 413
    assert "too large" in res.get_json()["error"].lower()


def test_dashboard_welcome_on_empty_db(web_client):
    html = web_client.get("/dashboard").get_data(as_text=True)
    assert "Run Your First Scan" in html
    assert "welcome-banner" in html


def test_dashboard_no_welcome_when_jobs_exist(web_client):
    from models.job import JobRecord, save_job
    save_job(JobRecord(title="T", company="C", description="x" * 50,
                       url="https://example.com/w", source="remotive"))
    html = web_client.get("/dashboard").get_data(as_text=True)
    assert "welcome-banner" not in html


def test_safe_defaults():
    assert config.SCAN_ENABLED is False
    assert config.FLASK_DEBUG is False
    assert config.SCAN_API_TOKEN == ""
    assert config.SCAN_ALLOW_ANONYMOUS is False
    assert config.RATE_LIMIT_ANALYZE and config.RATE_LIMIT_SCAN
    assert config.RATE_LIMIT_READ


def test_deploy_files_exist():
    root = config.APP_DIR
    env_example = os.path.join(root, ".env.example")
    dockerfile = os.path.join(root, "Dockerfile")
    assert os.path.exists(env_example)
    env_content = open(env_example).read()
    for key in ("SCAN_ENABLED", "SCAN_API_TOKEN", "SCAN_ALLOW_ANONYMOUS",
                "RATE_LIMIT_ANALYZE", "RATE_LIMIT_SCAN", "RATE_LIMIT_READ"):
        assert key in env_content, key
    assert os.path.exists(dockerfile)
    content = open(dockerfile).read()
    assert "gunicorn" in content and "app:app" in content
    # Hardening: pinned base, non-root runtime user, healthcheck on /api/health.
    assert "python:3.12-slim-bookworm" in content
    assert "USER appuser" in content
    assert "HEALTHCHECK" in content and "/api/health" in content
    reqs = open(os.path.join(root, "requirements.txt")).read()
    assert "gunicorn" in reqs
    assert "Flask-Limiter" in reqs
    readme = open(os.path.join(root, "README.md")).read()
    for keyword in ("/dashboard", "SCAN_ENABLED", "/api/scan", "remoteok",
                    "arbeitnow", "jobicy", "pytest", "gunicorn", ".env.example"):
        assert keyword.lower() in readme.lower(), keyword
