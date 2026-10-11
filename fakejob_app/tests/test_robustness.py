"""Freeze-pass robustness: hostile inputs must never crash the system."""

import pytest

import config
from models.job import JobRecord, get_job, init_db, list_jobs, save_job
from risk.actions import generate_actions
from risk.engine import assess_risk
from risk.freshness import freshness_status, job_age_days, parse_posted_at
from risk.indicators import analyze_indicators
from risk.language import check_language
from risk.verification import verify_employer

TEXT = ("Support Engineer at Acme Corp. Help customers via email and chat. "
        "Requirements: 2 years experience. Salary $60,000. Apply now.")
SCAM = ("Pay a refundable registration fee of $50. Send bank account number. "
        "Apply immediately! Contact x@gmail.com. Company: Global Data Ltd. "
        "Develop software with the team using modern tools daily.")

HOSTILE_METAS = [
    None, {}, {"posted_at": None}, {"posted_at": "garbage"},
    {"posted_at": object()}, {"posted_at": -5}, {"posted_at": "99999999999999999"},
    {"posted_at": "2026-13-45"}, {"posted_at": 0}, {"posted_at": [2026]},
    {"posted_at": "2026-01-01", "now": "junk"}, {"now": object()},
]


@pytest.mark.parametrize("meta", HOSTILE_METAS)
def test_hostile_metadata_never_crashes(meta):
    fired = analyze_indicators(TEXT, meta)
    result = assess_risk(fired)
    assert result["overall_risk_level"] in ("Low", "Medium", "High", "Critical")
    assert check_language(result["summary"]) == []
    verify_employer(TEXT, fired)
    generate_actions(fired, result["overall_risk_level"])


@pytest.mark.parametrize("meta", HOSTILE_METAS)
def test_critical_dominates_whatever_the_metadata(meta):
    result = assess_risk(analyze_indicators(SCAM, meta))
    assert result["overall_risk_level"] == "Critical"


def test_minimal_indicator_dicts():
    result = assess_risk([{}, {"id": "H1"}])
    assert result["overall_risk_level"] in ("Low", "Medium", "High", "Critical")
    verify_employer("", None)
    generate_actions(None, "Low")
    assert parse_posted_at(object()) is None
    assert job_age_days("garbage") is None
    assert freshness_status(object())["band"] == "unknown"


def test_malformed_scanner_payloads_never_raise(monkeypatch):
    from scanner.remoteok import RemoteOKScanner
    from scanner.remotive import RemotiveScanner
    from scanner.arbeitnow import ArbeitnowScanner
    from scanner.jobicy import JobicyScanner

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    for scanner in (RemoteOKScanner(), RemotiveScanner(), ArbeitnowScanner(), JobicyScanner()):
        for bad in (None, [], {}, {"jobs": None}, {"data": None},
                    [{"position": None, "url": 123}], "junk"):
            monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: Resp(bad))
            assert scanner.safe_fetch(3) == []


def test_bad_pagination_params_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "r.db"))
    init_db(config.DATABASE_PATH)
    assert list_jobs(limit="abc", offset="xyz", db_path=config.DATABASE_PATH) == []
    assert list_jobs(limit=-5, db_path=config.DATABASE_PATH) == []


def test_jobs_api_bad_limit_still_200(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "r2.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        assert client.get("/api/jobs?limit=abc&offset=-3").status_code == 200


def test_db_connections_are_closed(tmp_path, monkeypatch):
    """A regression guard for the sqlite connection leak: repeated calls must
    not leave connections/fds open."""
    import gc
    import sqlite3
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "leak.db"))
    init_db(config.DATABASE_PATH)
    for _ in range(50):
        list_jobs(db_path=config.DATABASE_PATH)
        get_job(1, db_path=config.DATABASE_PATH)
    # Find any tracked connection that is still open.
    gc.collect()
    open_conns = 0
    for obj in gc.get_objects():
        if isinstance(obj, sqlite3.Connection):
            try:
                obj.execute("SELECT 1")
                open_conns += 1
            except sqlite3.ProgrammingError:
                pass
    assert open_conns == 0


def test_db_write_persists_across_reconnect(tmp_path, monkeypatch):
    """_connect no longer commits implicitly, so writers must commit. Prove a
    written row survives the connection close and is visible on reconnect."""
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "persist.db"))
    init_db(config.DATABASE_PATH)
    job_id = save_job(
        JobRecord(title="Backend Engineer", company="Acme",
                  url="https://example.com/job/1"),
        db_path=config.DATABASE_PATH,
    )
    assert job_id > 0
    reopened = get_job(job_id, db_path=config.DATABASE_PATH)
    assert reopened is not None
    assert reopened["title"] == "Backend Engineer"
    assert reopened["company"] == "Acme"


def test_normalize_url_rejects_dangerous_schemes():
    from scanner.base import normalize_url
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("data:text/html,<script>1</script>") == ""
    assert normalize_url("file:///etc/passwd") == ""
    assert normalize_url("https://example.com/job/1") == "https://example.com/job/1"
