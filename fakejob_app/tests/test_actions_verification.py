"""Tests for actions generator and employer verification."""

from risk.actions import generate_actions
from risk.verification import verify_employer


def _mk(ind_id, severity="High"):
    return {"id": ind_id, "name": "n", "severity": severity,
            "category": "Suspicious", "evidence": "e", "explanation": "x"}


def test_critical_actions_lead_with_safety():
    actions = generate_actions([_mk("C1", "Critical")], "Critical")
    assert 3 <= len(actions) <= 5
    assert "payment" in actions[0].lower() or "fee" in actions[0].lower()


def test_low_actions_non_alarmist():
    actions = generate_actions([], "Low")
    assert 3 <= len(actions) <= 3
    joined = " ".join(actions).lower()
    assert "do not send" not in joined


def test_verification_never_invents():
    v = verify_employer("Hello world, no company, no contacts.")
    assert v["company_website"] in ("Found", "Not found", "Could not check")
    assert v["email_domain_match"] in ("Yes", "No", "N/A")
    assert v["role_on_careers_page"] in ("Yes", "No", "Unknown")
    assert isinstance(v["notes"], str) and v["notes"]
