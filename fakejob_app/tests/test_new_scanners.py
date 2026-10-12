"""Tests for the expanded no-auth source set (network fully mocked).

Covers the six added scanners (Himalayas, Working Nomads, LaraJobs, Greenhouse,
Lever, Ashby): fixture parsing, registry wiring, per-board isolation, malformed
payload tolerance, and mixed-source orchestration.
"""

import pytest

import config
from scanner import get_scanner, list_sources
from scanner.ashby import AshbyScanner
from scanner.greenhouse import GreenhouseScanner
from scanner.himalayas import HimalayasScanner
from scanner.larajobs import LaraJobsScanner
from scanner.lever import LeverScanner
from scanner.workingnomads import WorkingNomadsScanner

NEW_SOURCES = ["himalayas", "workingnomads", "larajobs",
               "greenhouse", "lever", "ashby"]
EXISTING_SOURCES = ["remoteok", "remotive", "arbeitnow", "jobicy"]


class _Resp:
    """Minimal stand-in for requests.Response (json + raw content)."""

    def __init__(self, payload=None, content=b"", status=200):
        self._payload = payload
        self.content = content if isinstance(content, bytes) else str(content).encode()
        self.status_code = status
        self.text = self.content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# --- registry ------------------------------------------------------------

def test_registry_lists_ten_sources():
    names = set(list_sources())
    assert set(EXISTING_SOURCES) <= names
    assert set(NEW_SOURCES) <= names
    assert len(names) == 10


def test_registry_instantiates_new_scanners():
    assert isinstance(get_scanner("himalayas"), HimalayasScanner)
    assert isinstance(get_scanner("workingnomads"), WorkingNomadsScanner)
    assert isinstance(get_scanner("larajobs"), LaraJobsScanner)
    assert isinstance(get_scanner("greenhouse"), GreenhouseScanner)
    assert isinstance(get_scanner("lever"), LeverScanner)
    assert isinstance(get_scanner("ashby"), AshbyScanner)


# --- per-source normalization -------------------------------------------

def test_himalayas_normalizes(monkeypatch):
    payload = {"jobs": [{
        "title": "Data Engineer", "companyName": "Hapi",
        "locationRestrictions": ["United States", "Canada"],
        "description": "<p>Build <b>pipelines</b></p>",
        "applicationLink": "https://himalayas.app/companies/hapi/jobs/de",
        "guid": "https://himalayas.app/companies/hapi/jobs/de",
        "pubDate": 1700000000,
    }]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = HimalayasScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == ("Data Engineer", "Hapi", "himalayas")
    assert "United States" in j.location and "Canada" in j.location
    assert "pipelines" in j.description and "<" not in j.description
    assert j.posted_at.startswith("2023")


def test_workingnomads_normalizes(monkeypatch):
    payload = [{
        "url": "https://www.workingnomads.com/job/go/1/",
        "title": "Backend Engineer",
        "description": "<h3>About us</h3><p>Build APIs</p>",
        "company_name": "Proxify", "location": "Remote",
        "pub_date": "2026-01-02T00:00:00+00:00",
    }]
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = WorkingNomadsScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == ("Backend Engineer", "Proxify", "workingnomads")
    assert "APIs" in j.description and "<" not in j.description


def test_workingnomads_has_timeout_floor():
    assert WorkingNomadsScanner().timeout >= config.WORKINGNOMADS_TIMEOUT


LARA_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:larajobs="https://larajobs.com">
<channel><item>
  <title>Senior Laravel Engineer</title>
  <link>https://larajobs.com/job/1</link>
  <pubDate>Tue, 06 Oct 2026 19:24:09 +0000</pubDate>
  <dc:creator>Resource Innovations</dc:creator>
  <larajobs:company>Resource Innovations</larajobs:company>
  <larajobs:location>Remote/USA</larajobs:location>
  <content:encoded><![CDATA[<p>Build <b>Laravel</b> apps at scale</p>]]></content:encoded>
</item></channel></rss>"""


def test_larajobs_parses_rss(monkeypatch):
    monkeypatch.setattr("scanner.base.requests.get",
                        lambda *a, **k: _Resp(content=LARA_RSS))
    jobs = LaraJobsScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == (
        "Senior Laravel Engineer", "Resource Innovations", "larajobs")
    assert j.location == "Remote/USA"
    assert "Laravel" in j.description and "<" not in j.description
    assert j.url == "https://larajobs.com/job/1"


def test_greenhouse_normalizes_escaped_html(monkeypatch):
    monkeypatch.setattr(config, "GREENHOUSE_BOARDS", ["acme"])
    payload = {"jobs": [{
        "title": "Account Executive", "company_name": "Acme",
        "location": {"name": "Hybrid - London"},
        "content": "&lt;div&gt;&lt;p&gt;Sell &amp; close deals&lt;/p&gt;&lt;/div&gt;",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "first_published": "2026-08-06T12:50:10-04:00",
    }]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = GreenhouseScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == ("Account Executive", "Acme", "greenhouse")
    assert j.location == "Hybrid - London"
    assert "Sell & close deals" in j.description and "<" not in j.description
    assert j.posted_at.startswith("2026")


def test_lever_normalizes(monkeypatch):
    monkeypatch.setattr(config, "LEVER_BOARDS", ["dnb"])
    payload = [{
        "text": "Database Administrator",
        "hostedUrl": "https://jobs.lever.co/dnb/abc",
        "createdAt": 1790352226883,
        "categories": {"location": "Warsaw - Poland", "team": "Technology"},
        "descriptionPlain": "Shape the future with reliable data platforms.",
    }]
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = LeverScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Database Administrator" and j.source == "lever"
    assert j.company == "dnb" and "Poland" in j.location
    assert j.posted_at.startswith("2026")


def test_ashby_normalizes(monkeypatch):
    monkeypatch.setattr(config, "ASHBY_BOARDS", ["openai"])
    payload = {"apiVersion": "1", "jobs": [{
        "title": "Technical Program Manager",
        "location": "San Francisco", "isRemote": True,
        "publishedAt": "2026-03-12T16:38:15.322+00:00",
        "jobUrl": "https://jobs.ashbyhq.com/openai/abc",
        "descriptionPlain": "Run large-scale compute infrastructure.",
    }]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = AshbyScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Technical Program Manager" and j.source == "ashby"
    assert j.company == "openai" and "Remote" in j.location
    assert j.posted_at.startswith("2026")


# --- isolation & robustness ---------------------------------------------

def test_board_scanner_isolates_bad_token(monkeypatch):
    monkeypatch.setattr(config, "GREENHOUSE_BOARDS", ["down", "good"])
    good = {"jobs": [{"title": "Backend Dev", "company_name": "Acme",
                      "location": {"name": "Remote"},
                      "content": "Build backend services.",
                      "absolute_url": "https://boards.greenhouse.io/acme/1"}]}

    def fake_get(url, *a, **k):
        if "down" in url:
            raise ConnectionError("board down")
        return _Resp(good)

    monkeypatch.setattr("scanner.base.requests.get", fake_get)
    monkeypatch.setattr("scanner.base.time.sleep", lambda s: None)
    jobs = GreenhouseScanner().safe_fetch(5)
    assert len(jobs) == 1 and jobs[0].title == "Backend Dev"


@pytest.mark.parametrize("cls", [HimalayasScanner, WorkingNomadsScanner,
                                 LaraJobsScanner, GreenhouseScanner,
                                 LeverScanner, AshbyScanner])
def test_invalid_payload_never_crashes(monkeypatch, cls):
    monkeypatch.setattr(config, "GREENHOUSE_BOARDS", ["x"])
    monkeypatch.setattr(config, "LEVER_BOARDS", ["x"])
    monkeypatch.setattr(config, "ASHBY_BOARDS", ["x"])
    monkeypatch.setattr("scanner.base.time.sleep", lambda s: None)
    # 200 OK but garbage body / unexpected shape.
    monkeypatch.setattr("scanner.base.requests.get",
                        lambda *a, **k: _Resp(payload={"unexpected": 1},
                                              content=b"<<not xml at all"))
    assert cls().safe_fetch(5) == []


def test_network_error_yields_empty(monkeypatch):
    monkeypatch.setattr(config, "GREENHOUSE_BOARDS", ["x"])
    monkeypatch.setattr("scanner.base.time.sleep", lambda s: None)

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr("scanner.base.requests.get", boom)
    for cls in (HimalayasScanner, WorkingNomadsScanner, LaraJobsScanner,
                GreenhouseScanner, LeverScanner, AshbyScanner):
        assert cls().safe_fetch(5) == []


# --- orchestration -------------------------------------------------------

def test_api_sources_endpoint_lists_all(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "src.db"))
    from models.job import init_db
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as client:
        body = client.get("/api/sources").get_json()
    assert set(NEW_SOURCES) <= set(body["sources"])
    assert len(body["sources"]) == 10


def test_run_scan_with_mixed_new_sources(tmp_path, monkeypatch):
    import services.scanner_service as svc
    from scanner.base import NormalizedJob

    store = {
        "himalayas": [NormalizedJob(
            title="Data Engineer", company="Hapi", location="Remote",
            description="Build data pipelines and streaming systems daily.",
            url="https://himalayas.app/companies/hapi/jobs/de", source="himalayas")],
        "greenhouse": [NormalizedJob(
            title="Backend Engineer", company="Acme", location="Remote",
            description="Design distributed backend services and APIs.",
            url="https://boards.greenhouse.io/acme/jobs/1", source="greenhouse")],
    }

    class FakeScanner:
        def __init__(self, name):
            self.name = name

        def safe_fetch(self, limit=20):
            return list(store[self.name])

    monkeypatch.setattr(svc, "get_scanner", lambda name, **k: FakeScanner(name))
    summary = svc.run_scan(sources=["himalayas", "greenhouse"],
                           limit_per_source=5, db_path=str(tmp_path / "mix.db"))
    assert summary["stored"] == 2
    assert summary["sources"] == {"himalayas": 1, "greenhouse": 1}
    assert summary["status"] in ("success", "partial")
