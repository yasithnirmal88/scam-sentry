"""Tests for deterministic safety-net checks (risk/consistency.py)."""

from risk.consistency import verify_assessment
from risk.engine import assess_risk


def _mk(ind_id, severity="High", category="Suspicious", evidence="some quoted evidence here"):
    return {"id": ind_id, "name": "N", "severity": severity,
            "category": category, "evidence": evidence, "explanation": "x"}


def test_clean_pass_has_no_corrections():
    fired = [_mk("H1"), _mk("H2")]
    assessment = assess_risk(fired)
    assert assessment["corrections"] == []
    assert assessment["overall_risk_level"] == "High"


def test_v1_critical_floor_forces_critical():
    fired = [_mk("C2", "Critical", "Scam Indicators")]
    tampered = {"overall_risk_level": "Low", "risk_categories": ["Likely Genuine"],
                "confidence": "Low", "summary": "All good.", "key_indicators": fired}
    fixed, corrections = verify_assessment(fired, tampered)
    assert fixed["overall_risk_level"] == "Critical"
    assert "V1-critical-floor" in corrections
    # Dependent fields rebuilt, not left stale.
    assert fixed["confidence"] in ("High", "Medium")
    assert "Likely Genuine" not in fixed["risk_categories"]


def test_v2_impersonation_pair_raises_from_low():
    fired = [_mk("H1", "High", "Scam Indicators"), _mk("H4", "High", "Scam Indicators")]
    # Craft a Low verdict directly to exercise the net (the engine itself
    # would already call this High via the >=2-High rule).
    tampered = {"overall_risk_level": "Low", "risk_categories": [],
                "confidence": "Low", "summary": "All good.", "key_indicators": fired}
    fixed, corrections = verify_assessment(fired, tampered)
    assert fixed["overall_risk_level"] == "Medium"
    assert "V2-impersonation-pair" in corrections


def test_v2_does_not_fire_without_pair():
    fired = [_mk("H1", "High", "Scam Indicators"),
             _mk("M1", "Medium", "Suspicious"),
             _mk("M2", "Medium", "Suspicious")]
    assessment = assess_risk(fired)
    assert "V2-impersonation-pair" not in assessment["corrections"]


def test_v3_repairs_banned_summary():
    fired = [_mk("H2")]
    tampered = {"overall_risk_level": "Medium", "risk_categories": ["Suspicious"],
                "confidence": "Medium", "summary": "This is a scam, avoid it.",
                "key_indicators": fired}
    fixed, corrections = verify_assessment(fired, tampered)
    assert "V3-language-repair" in corrections
    assert "This is a scam" not in fixed["summary"]
    assert fixed["overall_risk_level"] == "Medium"  # level untouched


def test_assess_risk_output_shape_unchanged():
    assessment = assess_risk([])
    for key in ("overall_risk_level", "risk_categories", "confidence",
                "summary", "key_indicators"):
        assert key in assessment
