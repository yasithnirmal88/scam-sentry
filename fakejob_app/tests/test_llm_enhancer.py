"""Tests for the optional LLM enhancement layer (network fully mocked).

The layer must never decide or change the risk level, must obey language
discipline, and must degrade silently to the engine output on any failure.
"""

import config
from risk import llm_enhancer as le

CFG = {
    "base_url": "https://example.test/v1",
    "api_key": "test-key",
    "model": "test-model",
    "timeout": 3,
    "max_tokens": 128,
    "temperature": 0.1,
}

RISK = {
    "overall_risk_level": "High",
    "risk_categories": ["Scam Indicators"],
    "confidence": "Medium",
    "summary": "Engine summary text.",
    "key_indicators": [
        {"id": "H2", "name": "Strong urgency language", "severity": "High",
         "evidence": "apply within 24 hours"},
    ],
}

POSTING = ("We are hiring urgently. Apply within 24 hours. Contact "
           "hr@example.com. Salary negotiable. No experience required.")


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %d" % self.status_code)

    def json(self):
        return self._payload


def _reply(content):
    return {"choices": [{"message": {"content": content}}]}


# --------------------------------------------------------------------------
# Config / enablement
# --------------------------------------------------------------------------

def test_is_enabled_default_false(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    assert le.is_enabled() is False


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    assert le.enhance(RISK, POSTING) is None


# --------------------------------------------------------------------------
# Happy path / parsing
# --------------------------------------------------------------------------

def test_enhance_success(monkeypatch):
    content = '{"summary": "Rewritten clearly.", "explanation": "Because H2."}'
    monkeypatch.setattr(le.requests, "post", lambda *a, **k: _Resp(_reply(content)))
    out = le.enhance(RISK, POSTING, cfg=CFG)
    assert out is not None
    assert out["summary"] == "Rewritten clearly."
    assert out["explanation"] == "Because H2."
    assert out["model"] == "test-model"


def test_enhance_sends_expected_request(monkeypatch):
    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Resp(_reply('{"summary": "S.", "explanation": "E."}'))

    monkeypatch.setattr(le.requests, "post", _fake_post)
    le.enhance(RISK, POSTING, cfg=CFG)
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "test-model"
    assert captured["timeout"] == 3
    assert captured["json"]["messages"][0]["role"] == "system"


def test_enhance_tolerates_code_fence(monkeypatch):
    content = '```json\n{"summary": "S.", "explanation": "E."}\n```'
    monkeypatch.setattr(le.requests, "post", lambda *a, **k: _Resp(_reply(content)))
    out = le.enhance(RISK, POSTING, cfg=CFG)
    assert out["summary"] == "S."


def test_enhance_plain_text_fallback(monkeypatch):
    monkeypatch.setattr(le.requests, "post",
                        lambda *a, **k: _Resp(_reply("Just one plain sentence.")))
    out = le.enhance(RISK, POSTING, cfg=CFG)
    assert out["summary"] == "Just one plain sentence."
    assert out["explanation"] == ""


# --------------------------------------------------------------------------
# Failure handling (graceful fallback)
# --------------------------------------------------------------------------

def test_request_exception_returns_none(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(le.requests, "post", boom)
    assert le.enhance(RISK, POSTING, cfg=CFG) is None


def test_http_error_returns_none(monkeypatch):
    monkeypatch.setattr(le.requests, "post",
                        lambda *a, **k: _Resp(_reply("{}"), status=500))
    assert le.enhance(RISK, POSTING, cfg=CFG) is None


def test_empty_content_returns_none(monkeypatch):
    monkeypatch.setattr(le.requests, "post",
                        lambda *a, **k: _Resp({"choices": []}))
    assert le.enhance(RISK, POSTING, cfg=CFG) is None


def test_missing_model_returns_none():
    assert le.enhance(RISK, POSTING, cfg={"base_url": "https://x/v1", "model": ""}) is None


# --------------------------------------------------------------------------
# Safety: language discipline + Critical protection
# --------------------------------------------------------------------------

def test_rejects_banned_phrasing(monkeypatch):
    content = '{"summary": "This is a scam.", "explanation": "Trust me."}'
    monkeypatch.setattr(le.requests, "post", lambda *a, **k: _Resp(_reply(content)))
    assert le.enhance(RISK, POSTING, cfg=CFG) is None


def test_rejects_critical_softening(monkeypatch):
    critical = dict(RISK, overall_risk_level="Critical")
    content = '{"summary": "This posting shows low risk overall.", "explanation": "x"}'
    monkeypatch.setattr(le.requests, "post", lambda *a, **k: _Resp(_reply(content)))
    assert le.enhance(critical, POSTING, cfg=CFG) is None


def test_accepts_critical_without_softening(monkeypatch):
    critical = dict(RISK, overall_risk_level="Critical")
    content = ('{"summary": "High risk: this posting shows critical advance-fee '
               'patterns.", "explanation": "C1 fired on a fee request."}')
    monkeypatch.setattr(le.requests, "post", lambda *a, **k: _Resp(_reply(content)))
    out = le.enhance(critical, POSTING, cfg=CFG)
    assert out is not None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def test_build_user_prompt_includes_level_and_indicators():
    prompt = le.build_user_prompt(RISK, POSTING)
    assert "High" in prompt
    assert "H2" in prompt
    assert POSTING[:20] in prompt


def test_endpoint_helper():
    assert le._endpoint("https://x/v1") == "https://x/v1/chat/completions"
    assert le._endpoint("https://x/v1/chat/completions") == "https://x/v1/chat/completions"
    assert le._endpoint("") == ""


# --------------------------------------------------------------------------
# Integration with app.classify
# --------------------------------------------------------------------------

def test_classify_without_llm_keeps_engine_summary(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    import app as app_module
    result = app_module.classify(POSTING)
    assert result["llm_enhanced"] is False
    assert result["llm_explanation"] is None
    assert result["summary"] == result["engine_summary"]


def test_classify_with_llm_merges_summary(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr("risk.llm_enhancer.enhance",
                        lambda rr, text, cfg=None: {
                            "summary": "LLM improved summary.",
                            "explanation": "LLM reasoning.",
                            "model": "mock-model"})
    import app as app_module
    result = app_module.classify(POSTING, use_llm=True)
    assert result["llm_enhanced"] is True
    assert result["summary"] == "LLM improved summary."
    assert result["llm_explanation"] == "LLM reasoning."
    assert result["llm_model"] == "mock-model"
    # The verdict itself is untouched by the enhancer.
    assert result["overall_risk_level"] == app_module.classify(POSTING, use_llm=False)["overall_risk_level"]


def test_classify_llm_failure_falls_back(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", True)

    def boom(rr, text, cfg=None):
        raise RuntimeError("llm exploded")

    monkeypatch.setattr("risk.llm_enhancer.enhance", boom)
    import app as app_module
    result = app_module.classify(POSTING, use_llm=True)
    assert result["llm_enhanced"] is False
    assert result["summary"] == result["engine_summary"]
