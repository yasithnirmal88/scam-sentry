"""Tests for determination rules (first match wins) and language discipline."""

from risk.engine import assess_risk, evidence_is_direct, has_critical


def _mk(ind_id, severity="High", category="Suspicious", name="X", evidence="e"):
    return {"id": ind_id, "name": name, "severity": severity,
            "category": category, "evidence": evidence, "explanation": "x"}


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


def test_has_critical_helper():
    assert has_critical([_mk("C1", "Critical", "Scam Indicators")]) is True
    assert has_critical([_mk("H1")]) is False
    assert has_critical([]) is False


def test_evidence_directness():
    assert evidence_is_direct({"evidence": "pay a refundable registration fee now"}) is True
    assert evidence_is_direct({"evidence": "short"}) is False
    assert evidence_is_direct({}) is False
    assert evidence_is_direct(None) is False


def test_single_critical_direct_evidence_is_high_confidence():
    fired = [_mk("C1", "Critical", "Scam Indicators",
                 evidence="all applicants must pay a refundable registration fee")]
    result = assess_risk(fired)
    assert result["overall_risk_level"] == "Critical"
    assert result["confidence"] == "High"


def test_single_critical_weak_evidence_is_medium_confidence():
    fired = [_mk("C1", "Critical", "Scam Indicators", evidence="fee")]
    result = assess_risk(fired)
    assert result["overall_risk_level"] == "Critical"
    assert result["confidence"] == "Medium"


def test_confidence_multiple_strong_agree():
    fired = [_mk("H1"), _mk("H2")]
    assert assess_risk(fired)["confidence"] == "High"


def test_confidence_partial_evidence():
    assert assess_risk([_mk("H2")])["confidence"] == "Medium"
    assert assess_risk([_mk("M1", "Medium"), _mk("M2", "Medium")])["confidence"] == "Medium"


def test_confidence_weak_evidence_only():
    assert assess_risk([_mk("L1", "Low")])["confidence"] == "Low"


def test_confidence_empty_is_capped_medium():
    assert assess_risk([])["confidence"] == "Medium"


def test_summaries_allow_legitimate_explanations():
    for fired in ([_mk("C1", "Critical", "Scam Indicators")],
                  [_mk("H1"), _mk("H2")],
                  [_mk("M1", "Medium")],
                  [_mk("L2", "Low")]):
        assert "could also be explained by" in assess_risk(fired)["summary"]
