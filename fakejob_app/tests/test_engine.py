"""Tests for determination rules (first match wins) and language discipline."""

from risk.engine import assess_risk


def _mk(ind_id, severity="High", category="Suspicious", name="X"):
    return {"id": ind_id, "name": name, "severity": severity,
            "category": category, "evidence": "e", "explanation": "x"}


def test_any_critical_forces_critical():
    fired = [_mk("C1", "Critical", "Scam Indicators")]
    assert assess_risk(fired)["overall_risk_level"] == "Critical"


def test_two_high_is_high():
    fired = [_mk("H1", "High"), _mk("H2", "High")]
    assert assess_risk(fired)["overall_risk_level"] == "High"


def test_one_high_two_medium_is_high():
    fired = [_mk("H2", "High"), _mk("M1", "Medium"), _mk("M2", "Medium")]
    assert assess_risk(fired)["overall_risk_level"] == "High"


def test_one_high_alone_is_medium():
    fired = [_mk("H2", "High")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


def test_two_medium_is_medium():
    fired = [_mk("M1", "Medium"), _mk("M2", "Medium")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


def test_h5_alone_is_medium():
    fired = [_mk("H5", "High", "Ghost/Stale")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


def test_none_is_low():
    r = assess_risk([])
    assert r["overall_risk_level"] == "Low"
    assert "Likely Genuine" in r["risk_categories"]


def test_language_discipline():
    fired = [_mk("C1", "Critical", "Scam Indicators", name="Advance fee requested")]
    summary = assess_risk(fired)["summary"].lower()
    assert "this is a scam" not in summary
    assert "this is fake" not in summary
