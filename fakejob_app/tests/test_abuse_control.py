"""Phase 5 (abuse & cost control): scan-token auth, rate limits, startup
refusal for an un-hardened LLM config, and Content-Security-Policy headers.

Endpoints under test need a real app client; the shared limiter is normally
disabled in fixtures so unrelated tests are deterministic, and re-enabled only
inside the dedicated 429 tests.
"""

import pytest
from flask import Flask
from flask import request as flask_request
from flask_limiter.util import get_remote_address

import config
from models.job import JobRecord, init_db, save_job


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", False)
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as c:
        yield c


# --- scan-token auth -------------------------------------------------------

def test_scan_rejects_when_token_empty_and_anonymous_disabled(client, monkeypatch):
    """Fail-closed default: no token + SCAN_ALLOW_ANONYMOUS=false => 401."""
    init_db(config.DATABASE_PATH)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", False)
    res = client.post("/api/scan", json={"sources": ["bogus"]})
    assert res.status_code == 401
    assert "error" in res.get_json()
    # A stray header must not open the endpoint either.
    assert client.post(
        "/api/scan", json={}, headers={"X-Scan-Token": ""}).status_code == 401


def test_scan_allows_anonymous_when_explicitly_enabled(client, monkeypatch):
    """Explicit dev/demo opt-in: no token + SCAN_ALLOW_ANONYMOUS=true => open."""
    init_db(config.DATABASE_PATH)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", True)
    ok = client.post("/api/scan", json={"sources": ["bogus"]})
    assert ok.status_code == 400  # authorized: reached source validation


def test_scan_allows_valid_token(client, monkeypatch):
    """With a token configured, a matching X-Scan-Token is authorized."""
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "secret-token")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", False)
    ok = client.post("/api/scan", json={"sources": ["bogus"]},
                     headers={"X-Scan-Token": "secret-token"})
    assert ok.status_code == 400  # authenticated: proceeds to source validation


def test_scan_rejects_invalid_or_missing_token(client, monkeypatch):
    """With a token configured, a wrong/missing header is rejected (401)."""
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "secret-token")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", False)
    missing = client.post("/api/scan", json={})
    assert missing.status_code == 401
    wrong = client.post("/api/scan", json={}, headers={"X-Scan-Token": "wrong"})
    assert wrong.status_code == 401
    assert "error" in wrong.get_json()


def test_anonymous_flag_ignored_when_token_set(client, monkeypatch):
    """SCAN_ALLOW_ANONYMOUS must not bypass a configured token."""
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "secret-token")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", True)
    assert client.post("/api/scan", json={}).status_code == 401
    ok = client.post("/api/scan", json={"sources": ["bogus"]},
                     headers={"X-Scan-Token": "secret-token"})
    assert ok.status_code == 400


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


def test_read_endpoint_rate_limit_429(client, monkeypatch):
    """Public read routes are throttled with a clean JSON 429, and the limit
    is independent per route (so one hot route doesn't block the rest)."""
    import app as app_module
    app_module.limiter.enabled = True
    try:
        app_module.limiter.reset()
        monkeypatch.setattr(config, "RATE_LIMIT_READ", "2/minute")
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/jobs").status_code == 200
        blocked = client.get("/api/jobs")
        assert blocked.status_code == 429
        assert "error" in blocked.get_json()
        # A different read route has its own counter and still works.
        assert client.get("/api/taxonomy").status_code == 200
    finally:
        app_module.limiter.reset()
        app_module.limiter.enabled = False


def test_dashboard_page_rate_limit_429(client, monkeypatch):
    """Dashboard pages carry the same light read limit (clean 429)."""
    import app as app_module
    app_module.limiter.enabled = True
    try:
        app_module.limiter.reset()
        monkeypatch.setattr(config, "RATE_LIMIT_READ", "1/minute")
        assert client.get("/dashboard").status_code == 200
        blocked = client.get("/dashboard")
        assert blocked.status_code == 429
        assert "error" in blocked.get_json()
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


def test_anonymous_flag_cannot_bypass_llm_token_requirement(monkeypatch):
    """SCAN_ALLOW_ANONYMOUS must not let the spend path boot without a token."""
    import app as app_module
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "SCAN_API_TOKEN", "")
    monkeypatch.setattr(config, "SCAN_ALLOW_ANONYMOUS", True)
    monkeypatch.setattr(config, "RATE_LIMIT_ANALYZE", "30/minute")
    monkeypatch.setattr(config, "RATE_LIMIT_SCAN", "5/minute")
    with pytest.raises(SystemExit):
        app_module._assert_secure_startup()


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


# --- proxy-aware client IP for rate limiting (F-03) ------------------------
# Verification: the real ``apply_proxy_fix`` helper is applied to a probe app,
# and we assert that ``request.remote_addr`` (which Flask-Limiter's
# ``get_remote_address`` reads) resolves to the real client IP only when proxy
# headers are present and hops are trusted.

def _probe_client(monkeypatch, hops):
    import app as app_module
    monkeypatch.setattr(config, "TRUSTED_PROXY_HOPS", hops)
    probe = Flask("proxy-probe")

    @probe.route("/probe")
    def _probe():
        return {"remote_addr": flask_request.remote_addr,
                "limiter_key": get_remote_address()}

    app_module.apply_proxy_fix(probe)
    probe.config["TESTING"] = True
    return probe.test_client()


def test_proxy_fix_uses_forwarded_client_ip(monkeypatch):
    client = _probe_client(monkeypatch, 1)
    body = client.get("/probe", headers={"X-Forwarded-For": "203.0.113.7"}).get_json()
    assert body["remote_addr"] == "203.0.113.7"
    assert body["limiter_key"] == "203.0.113.7"


def test_proxy_fix_uses_rightmost_trusted_hop(monkeypatch):
    """A client-supplied leading value must not win over the proxy's value."""
    client = _probe_client(monkeypatch, 1)
    res = client.get("/probe",
                     headers={"X-Forwarded-For": "198.51.100.9, 203.0.113.7"})
    assert res.get_json()["remote_addr"] == "203.0.113.7"


def test_proxy_fix_disabled_when_no_hops_trusted(monkeypatch):
    client = _probe_client(monkeypatch, 0)
    body = client.get("/probe",
                      headers={"X-Forwarded-For": "203.0.113.7"}).get_json()
    assert body["remote_addr"] != "203.0.113.7"
    assert body["limiter_key"] != "203.0.113.7"


def test_proxy_fix_leaves_local_requests_untouched(monkeypatch):
    client = _probe_client(monkeypatch, 1)
    res = client.get("/probe")  # no proxy headers, as in local development
    assert res.get_json()["remote_addr"] in ("127.0.0.1", "::1", "localhost")