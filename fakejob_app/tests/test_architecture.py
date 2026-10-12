"""Architecture tests: one authoritative verdict, shared helpers, no drift.

These lock in the split between the two rule/indicator systems:

  * risk/indicators.py + risk/engine.py -> authoritative verdict
  * fraud_features.py                    -> ML feature support / hybrid signal

The Risk Engine's `overall_risk_level` must never be overridden by the ML
model or the legacy scoring path, and the helpers the two systems share must
be the same objects (no divergent copies).
"""

import pytest

CLEAN = (
    "Senior Backend Engineer at Northwind Traders Inc, based in Austin, USA. "
    "You will design and maintain REST APIs, review pull requests, and mentor "
    "engineers across the platform team. Day to day responsibilities include "
    "system design, improving developer tooling, and supporting an on-call "
    "rotation. Requirements: five years of experience with Python and "
    "PostgreSQL, strong communication skills, and a bachelor's degree in "
    "computer science or equivalent. We value collaboration and clear "
    "documentation. Apply through our careers page at "
    "https://northwindtraders.com/careers or email talent@northwindtraders.com."
)

SCAM = (
    "Work from home data entry assistants wanted. A refundable registration fee "
    "of $50 is required before you can start. Limited positions, apply "
    "immediately! Contact the recruiter to reserve your seat today."
)


class _FakeLow:
    """A model that is (over)confident a posting is Genuine."""

    def predict_proba(self, X):
        return [[0.99, 0.01]]


class _FakeHigh:
    """A model that is (over)confident a posting is Fake."""

    def predict_proba(self, X):
        return [[0.01, 0.99]]


# ---------------------------------------------------------------------------
# The Risk Engine owns the verdict
# ---------------------------------------------------------------------------

def test_overall_level_equals_engine_output():
    import app as app_module
    from risk.engine import assess_risk
    from risk.indicators import analyze_indicators

    for text in (CLEAN, SCAM):
        expected = assess_risk(analyze_indicators(text))["overall_risk_level"]
        assert app_module.classify(text)["overall_risk_level"] == expected


def test_engine_verdict_survives_a_genuine_biased_model(monkeypatch):
    # Even when the ML side says "definitely genuine", a Critical posting
    # stays Critical because the Risk Engine sets the verdict.
    import app as app_module
    app_module._ensure_model()
    monkeypatch.setattr(app_module, "_clf", _FakeLow())

    result = app_module.classify(SCAM)
    assert result["ml_raw_probability"] == pytest.approx(1.0, abs=0.05)
    assert result["overall_risk_level"] == "Critical"


def test_engine_verdict_survives_a_fake_biased_model(monkeypatch):
    # Even when the ML side says "definitely fake", a clean posting stays Low;
    # only the non-authoritative hybrid band may move.
    import app as app_module
    app_module._ensure_model()
    monkeypatch.setattr(app_module, "_clf", _FakeHigh())

    result = app_module.classify(CLEAN)
    assert result["ml_raw_probability"] == pytest.approx(99.0, abs=0.05)
    assert result["overall_risk_level"] == "Low"
    assert result["risk_level"] in ("MEDIUM", "HIGH")  # supporting band only


def test_legacy_hybrid_floor_cannot_change_the_verdict(monkeypatch):
    # Force the legacy feature path to claim a decisive "critical_hit". That
    # legitimately floors the hybrid supporting score, but must NOT leak into
    # the authoritative engine verdict for an otherwise clean posting.
    import app as app_module
    app_module._ensure_model()

    def fake_extract(text):
        return {
            "features": {},
            "indicators": [],
            "rule_score": 100,
            "company_detected": None,
            "critical_hit": True,
            "strong_hit": True,
        }

    monkeypatch.setattr(app_module, "extract_all_features", fake_extract)

    result = app_module.classify(CLEAN)
    assert result["overall_risk_level"] == "Low"   # engine unaffected
    assert result["risk_level"] == "HIGH"          # hybrid band floored
    assert result["prediction"] == "Fake"


def test_key_indicators_come_from_the_engine():
    import app as app_module
    from risk.indicators import analyze_indicators

    engine_ids = [d["id"] for d in analyze_indicators(SCAM)]
    result = app_module.classify(SCAM)
    reported_ids = [d["id"] for d in result["key_indicators"]]
    assert "C1" in reported_ids
    assert reported_ids == engine_ids


# ---------------------------------------------------------------------------
# Shared helpers: single source of truth (no divergent copies)
# ---------------------------------------------------------------------------

def test_shared_helpers_are_the_same_objects():
    import fraud_features as ff
    from risk import indicators as ri

    assert ri.normalize is ff.normalize
    assert ri.company_matches_domain is ff.company_matches_domain
    assert ri.extract_company_name is ff.extract_company_name
    assert ri.EMAIL_PATTERN is ff.EMAIL_PATTERN
    assert ri.URL_PATTERN is ff.URL_PATTERN


def test_company_matches_domain_clear_cases():
    from fraud_features import company_matches_domain as m

    assert m("Acme Corporation", "totallyunrelated.org") is False
    assert m("Acme Corporation", "acmecorporation.com") is True
    assert m("Acme Solutions Ltd", "acmesolutions.com") is True
    assert m("ABC", "xyzcorp.com") is True  # too short -> inconclusive


def test_h4_and_legacy_url_feature_agree():
    from fraud_features import detect_suspicious_url
    from risk.indicators import check_h4

    impersonation = ("Join Acme Corporation. Verify your account at "
                     "https://secure-verify-login.example.com")
    assert check_h4(impersonation)[0] is True
    assert detect_suspicious_url(impersonation, "Acme Corporation")["triggered"] is True

    matching = ("Company: Acme Corporation. Apply at "
                "https://acmecorporation.com/careers")
    assert check_h4(matching)[0] is False
    assert detect_suspicious_url(matching, "Acme Corporation")["triggered"] is False


# ---------------------------------------------------------------------------
# Backward-compatible response still intact
# ---------------------------------------------------------------------------

def test_response_shape_and_supporting_fields():
    import app as app_module

    result = app_module.classify(SCAM)
    for key in (
        "overall_risk_level", "risk_categories", "confidence", "summary",
        "key_indicators", "recommended_actions",
        "hybrid_score", "rule_score", "ml_score",
        "prediction", "risk_level", "indicators",
        "fake_probability", "confidence_score", "ml_raw_probability",
    ):
        assert key in result, key
    assert 0.0 <= result["hybrid_score"] <= 1.0
    assert result["prediction"] in ("Fake", "Genuine")
    assert result["overall_risk_level"] in ("Low", "Medium", "High", "Critical")
