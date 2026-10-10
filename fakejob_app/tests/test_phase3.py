"""Tests for Phase 3: retries, new sources, history, scheduler, async scan API."""

import pytest

import config
from models.job import get_last_scan, init_db, record_scan_run
from scanner import get_scanner, list_sources
from scanner.arbeitnow import ArbeitnowScanner
from scanner.base import http_get, normalize_url
from scanner.jobicy import JobicyScanner


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# --- http retry helper ---

def test_http_get_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("flaky")
        return _Resp({"ok": True})

    monkeypatch.setattr("scanner.base.requests.get", fake_get)
    monkeypatch.setattr("scanner.base.time.sleep", lambda s: None)
    assert http_get("https://example.com").json() == {"ok": True}
    assert calls["n"] == 3


def test_http_get_raises_after_retries(monkeypatch):
    monkeypatch.setattr("scanner.base.requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr("scanner.base.time.sleep", lambda s: None)
    with pytest.raises(ConnectionError):
        http_get("https://example.com")


# --- url normalization ---

def test_normalize_url():
    assert normalize_url("https://Example.com/jobs/1/?utm_source=x&utm_medium=y") == \
        "https://example.com/jobs/1"
    assert normalize_url("https://example.com/jobs/1") == \
        normalize_url("https://example.com/jobs/1/?fbclid=abc#frag")
    assert normalize_url("") == ""


# --- new sources ---

def test_new_sources_registered():
    assert {"remoteok", "remotive", "arbeitnow", "jobicy"} <= set(list_sources())
    assert isinstance(get_scanner("arbeitnow"), ArbeitnowScanner)
    assert isinstance(get_scanner("jobicy"), JobicyScanner)


def test_arbeitnow_normalizes(monkeypatch):
    payload = {"data": [{
        "slug": "dev-remote-1", "company_name": "Wayve", "title": "Dev",
        "description": "<p>Build things</p>", "url": "https://www.arbeitnow.com/jobs/x",
        "location": "Remote", "remote": True, "created_at": "1791600009"}]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = ArbeitnowScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == ("Dev", "Wayve", "arbeitnow")
    assert "Build things" in j.description and "<" not in j.description
    assert j.posted_at.startswith("2026")


def test_jobicy_normalizes(monkeypatch):
    payload = {"jobs": [{
        "id": "1", "url": "https://jobicy.com/jobs/1-x", "jobTitle": "AE",
        "companyName": "Juniper", "jobGeo": "USA", "jobDescription": "<p>Sell</p>",
        "pubDate": "2026-10-09T18:42:49+00:00"}]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = JobicyScanner().safe_fetch(5)
    assert len(jobs) == 1
    assert jobs[0].company == "Juniper" and jobs[0].source == "jobicy"


# --- scan history ---

def test_record_and_get_last_scan(tmp_path):
    db = str(tmp_path / "h.db")
    init_db(db)
    assert get_last_scan(db) is None
    rid = record_scan_run({"started_at": "2026-01-01", "sources": {"remotive": 2},
                           "fetched": 2, "evaluated": 2, "stored": 2,
                           "skipped": 0, "duplicates": 0, "status": "success",
                           "errors": {}}, db)
    assert rid > 0
    last = get_last_scan(db)
    assert last["status"] == "success" and last["stored"] == 2
    assert last["sources"] == ["remotive"]


# --- run_scan records history, dedupes, isolates failures ---

def test_run_scan_history_and_dedup(tmp_path, monkeypatch):
    import services.scanner_service as svc
    from scanner.base import NormalizedJob

    db = str(tmp_path / "s.db")
    dup_url = "https://example.com/j?utm_source=x"
    jobs = [
        NormalizedJob(title="A", company="C", location="R",
                      description="Pay a registration fee now. Apply immediately!",
                      url=dup_url, source="s1"),
        NormalizedJob(title="A", company="C", location="R",
                      description="Pay a registration fee now. Apply immediately!",
                      url="https://example.com/j", source="s1"),  # duplicate after normalize
        NormalizedJob(title="short", company="", location="",
                      description="hi", url="https://example.com/tiny", source="s1"),
    ]

    class FakeScanner:
        name = "s1"

        def safe_fetch(self, limit=20):
            return jobs

    def boom(name, **k):
        raise ValueError("nope")

    monkeypatch.setattr(svc, "get_scanner",
                        lambda name, **k: FakeScanner() if name == "s1" else boom(name))
    def fake_evaluate(title, company, location, description, posted_at=None):
        if len(description or "") < 15:
            raise ValueError("too short")
        return {"overall_risk_level": "Critical", "risk_categories": [],
                "confidence": "High", "summary": "s",
                "key_indicators": [], "recommended_actions": [],
                "employer_verification": {}, "hybrid_score": 0.9,
                "rule_score": 0.9, "ml_score": 0.9}

    monkeypatch.setattr(svc, "evaluate_job", fake_evaluate)
    summary = svc.run_scan(sources=["s1", "nope"], limit_per_source=5, db_path=db)
    assert summary["stored"] == 1
    assert summary["duplicates"] == 1
    assert summary["skipped"] == 1
    assert summary["status"] == "partial"
    assert "nope" in summary["errors"]
    last = get_last_scan(db)
    assert last and last["status"] == "partial" and last["stored"] == 1


# --- scheduler ---

@pytest.fixture()
def sched_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "sched.db"))
    init_db(config.DATABASE_PATH)
    import services.scheduler as sched
    # reset global flags in case another test left them set
    sched._stop_event.clear()
    yield sched
    sched._stop_event.clear()


def test_trigger_async_runs_and_records(sched_env, monkeypatch):
    import services.scanner_service as svc

    def fake_run(sources=None, limit_per_source=None, db_path=None):
        return {"started_at": "t", "finished_at": "t", "sources": {"s1": 1},
                "fetched": 1, "evaluated": 1, "stored": 1, "skipped": 0,
                "duplicates": 0, "errors": {}, "status": "success"}

    monkeypatch.setattr(svc, "run_scan", fake_run)
    res = sched_env.trigger_async(sources=["s1"], limit=5)
    assert res["accepted"] is True
    import time
    for _ in range(100):
        if not sched_env.is_running():
            break
        time.sleep(0.05)
    assert not sched_env.is_running()
    status = sched_env.get_status()
    assert status["status"] == "idle"
    assert "interval_hours" in status


def test_trigger_rejected_while_running(sched_env, monkeypatch):
    import threading
    import services.scanner_service as svc

    entered = threading.Event()
    release = threading.Event()

    def blocking_run(sources=None, limit_per_source=None, db_path=None):
        entered.set()
        release.wait(timeout=5)
        return {"started_at": "t", "finished_at": "t", "sources": {},
                "fetched": 0, "evaluated": 0, "stored": 0, "skipped": 0,
                "duplicates": 0, "errors": {}, "status": "success"}

    monkeypatch.setattr(svc, "run_scan", blocking_run)
    assert sched_env.trigger_async(sources=["s1"])["accepted"] is True
    assert entered.wait(timeout=5)
    second = sched_env.trigger_async(sources=["s1"])
    assert second["accepted"] is False
    assert sched_env.is_running()
    release.set()


# --- async scan API ---

@pytest.fixture()
def scan_api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "scan3.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def test_post_scan_async_202(scan_api, monkeypatch):
    import services.scheduler as sched
    monkeypatch.setattr(sched, "trigger_async",
                        lambda **k: {"accepted": True, "status": "running"})
    res = scan_api.post("/api/scan", json={"sources": ["remotive"], "limit": 5})
    assert res.status_code == 202
    assert res.get_json()["status"] == "running"


def test_post_scan_409_when_busy(scan_api, monkeypatch):
    import services.scheduler as sched
    monkeypatch.setattr(sched, "trigger_async",
                        lambda **k: {"accepted": False, "reason": "busy", "status": "running"})
    assert scan_api.post("/api/scan", json={}).status_code == 409


def test_scan_status_endpoint(scan_api, monkeypatch):
    import services.scheduler as sched
    monkeypatch.setattr(sched, "get_status",
                        lambda db_path=None: {"running": False, "status": "idle",
                                              "last_scan": None})
    res = scan_api.get("/api/scan/status")
    assert res.status_code == 200
    assert res.get_json()["status"] == "idle"


def test_dashboard_shows_scan_strip(scan_api):
    html = scan_api.get("/dashboard").get_data(as_text=True)
    assert "Total Jobs Stored" in html
    assert "Last Scan" in html
    assert "Never" in html


# --- CLI ---

def test_cli_list_sources(capsys):
    import scan as scan_cli
    assert scan_cli.main(["--list-sources"]) == 0
    out = capsys.readouterr().out
    assert "remotive" in out and "jobicy" in out and "arbeitnow" in out
