"""Phase 5 (abuse & cost control): scan-token auth, rate limits, startup
refusal for an un-hardened LLM config, and Content-Security-Policy headers.

Endpoints under test need a real app client; the shared limiter is normally
disabled in fixtures so unrelated tests are deterministic, and re-enabled only
inside the dedicated 429 tests.
"""

import pytest

import config
from models.job import JobRecord, init_db, save_job


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "abuse.db"))
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as c:
        yield c


# --- scan-token auth -------------------------------------------------------

def test_scan_requires_token(client, monkeypatch):
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "secret-token")
    assert client.post("/api/scan", json={}).status_code == 401
    wrong = client.post("/api/scan", json={}, headers={"X-Scan-Token": "wrong"})
    assert wrong.status_code == 401
    assert "error" in wrong.get_json()
    ok = client.post("/api/scan", json={"sources": ["bogus"]},
                     headers={"X-Scan-Token": "secret-token"})
    assert ok.status_code == 400  # authenticated: proceeds to source validation


def test_scan_open_without_token_in_dev_mode(client, monkeypatch):
    """No-token dev/demo mode: token unset + LLM off => scans run open."""
    init_db(config.DATABASE_PATH)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    ok = client.post("/api/scan", json={"sources": ["bogus"]})
    assert ok.status_code == 400  # authorized: proceeds to source validation


def test_scan_rejects_without_token_when_llm_enabled(client, monkeypatch):
    """Fail-closed with a spend path: token unset + LLM on => 401."""
    init_db(config.DATABASE_PATH)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    assert client.post("/api/scan", json={}).status_code == 401
    with_header = client.post("/api/scan", json={}, headers={"X-Scan-Token": ""})
    assert with_header.status_code == 401


# --- rate limiting (429) ---------------------------------------------------

def _analyze(client, text):
    return client.post("/api/analyze/text", json={"text": text})


def test_analyze_rate_limit_429(client, monkeypatch):
    import app as app_module
    app_module.limiter.enabled = True
    try:
        app_module.limiter.reset()
        monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "2/minute")
        text = ("Support Engineer at Acme Corp. Help customers via email and "
                "chat. Requirements: 2 years experience. Salary 60000. Apply.")
        assert _analyze(client, text).status_code == 200
        assert _analyze(client, text + " (second copy)").status_code == 200
        blocked = _analyze(client, text + " (third copy)")
        assert blocked.status_code == 429
        assert "error" in blocked.get_json()
    finally:
        app_module.limiter.reset()
        app_module.limiter.enabled = False


def test_scan_rate_limit_429(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "tok")
    app_module.limiter.enabled = True
    try:
        app_module.limiter.reset()
        monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "1/minute")
        first = client.post("/api/scan", json={"sources": ["bogus"]},
                            headers={"X-Scan-Token": "tok"})
        assert first.status_code == 400  # authenticated, unknown source
        blocked = client.post("/api/scan", json={"sources": ["remotive"]},
                              headers={"X-Scan-Token": "tok"})
        assert blocked.status_code == 429
    finally:
        app_module.limiter.reset()
        app_module.limiter.enabled = False


# --- startup refusal for an un-hardened LLM config -------------------------

def test_refuses_start_when_llm_enabled_without_token(monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "30/minute")
    monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "5/minute")
    with pytest.raises(SystemExit) as exc:
        app_module._assert_secure_startup()
    assert "SCAN_API_TOKEN" in str(exc.value)


def test_refuses_start_when_llm_enabled_without_limits(monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "tok")
    monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "")
    monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "5/minute")
    with pytest.raises(SystemExit) as exc:
        app_module._assert_secure_startup()
    assert "RATE_LIMIT" in str(exc.value)


def test_starts_when_llm_enabled_and_hardened(monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "tok")
    monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "30/minute")
    monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "5/minute")
    app_module._assert_secure_startup()  # must not raise


def test_no_startup_guard_when_llm_disabled(monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "")
    monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "")
    app_module._assert_secure_startup()  # must not raise


# --- Content-Security-Policy + page rendering ------------------------------

def test_csp_header_on_all_responses(client):
    for path in ("/", "/dashboard", "/api/health", "/api/jobs"):
        csp = client.get(path).headers.get("Content-Security-Policy")
        assert csp, path
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'self'" in csp


def test_dashboard_renders_with_csp(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Job Risk Dashboard" in html
    assert "dashboard.js" in html


def test_job_detail_renders_with_csp(client):
    jid = save_job(JobRecord(
        title="QA Engineer", company="Acme", location="Remote",
        description="Test software. Requirements: pytest experience.",
        url="https://example.com/qa-csp", source="jobicy",
        overall_risk_level="Medium", risk_categories=["Suspicious"],
        confidence="Medium",
        summary="Some suspicious characteristics were found.",
        hybrid_score=0.4, rule_score=0.3, ml_score=0.5))
    res = client.get(f"/dashboard/jobs/{jid}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Risk Report" in html
    assert "QA Engineer" in html
    assert res.headers.get("Content-Security-Policy")