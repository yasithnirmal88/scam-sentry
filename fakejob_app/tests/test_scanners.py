"""Tests for scanner normalization (network mocked)."""

from scanner import get_scanner, list_sources
from scanner.base import clean_html
from scanner.remoteok import RemoteOKScanner
from scanner.remotive import RemotiveScanner


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_sources_registered():
    assert "remoteok" in list_sources()
    assert "remotive" in list_sources()
    assert isinstance(get_scanner("remoteok"), RemoteOKScanner)
    assert isinstance(get_scanner("remotive"), RemotiveScanner)


def test_remoteok_normalizes(monkeypatch):
    payload = [
        {"legal": "skip me"},
        {"position": "Backend Dev", "company": "Acme", "location": "Remote",
         "description": "<p>Build <b>APIs</b></p>", "url": "https://remoteok.com/x",
         "epoch": 1700000000, "date": "2023-11-14"},
    ]
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = RemoteOKScanner().safe_fetch(5)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.source) == ("Backend Dev", "Acme", "remoteok")
    assert "<" not in j.description and "APIs" in j.description
    assert j.posted_at.startswith("2023")


def test_remotive_normalizes(monkeypatch):
    payload = {"jobs": [
        {"title": "Designer", "company_name": "Beta", "candidate_required_location": "EU",
         "description": "<p>Design things</p>", "url": "https://remotive.com/y",
         "publication_date": "2026-02-01"},
    ]}
    monkeypatch.setattr("scanner.base.requests.get", lambda *a, **k: _Resp(payload))
    jobs = RemotiveScanner().safe_fetch(5)
    assert len(jobs) == 1
    assert jobs[0].company == "Beta" and jobs[0].source == "remotive"


def test_safe_fetch_never_raises(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr("scanner.base.requests.get", boom)
    assert RemoteOKScanner().safe_fetch(5) == []


def test_clean_html():
    assert clean_html("<p>Hello &amp; <b>bye</b></p>").strip() == "Hello & bye"
    assert clean_html(None) == ""
