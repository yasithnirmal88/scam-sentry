"""App-level alignment: new Critical evidence forces the hybrid floor too."""

import config


def test_new_critical_forces_score_floor():
    import app as app_module

    # "cash the cheque ... wire the funds back" trips the new C4 detector
    # but none of the legacy critical_hit patterns: the floor must still
    # apply through has_critical alignment.
    text = (
        "Work-from-home payments assistant needed. Please cash the cheque "
        "we send you and wire the funds back minus your cut. No experience "
        "needed, start today with just your name and phone number."
    )
    result = app_module.classify(text)
    assert "error" not in result
    assert result["overall_risk_level"] == "Critical"
    assert result["hybrid_score"] >= 0.7
    assert any(k["id"] == "C4" for k in result["key_indicators"])


def test_legacy_critical_still_floors():
    import app as app_module

    text = ("Data entry operator wanted. All applicants must pay a refundable "
            "registration fee of $50 before the interview. Apply now.")
    result = app_module.classify(text)
    assert result["overall_risk_level"] == "Critical"
    assert result["hybrid_score"] >= 0.7
