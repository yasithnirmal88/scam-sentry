"""Tests for risk indicators (pure, deterministic)."""

from risk.indicators import analyze_indicators


def test_c1_advance_fee_fires():
    text = "You must pay a refundable registration fee of $50 before the interview."
    ids = {d["id"] for d in analyze_indicators(text)}
    assert "C1" in ids


def test_c2_sensitive_data_fires():
    text = "Please send your bank account number and NIC copy to confirm your slot."
    ids = {d["id"] for d in analyze_indicators(text)}
    assert "C2" in ids


def test_c3_guarantee_plus_pressure():
    text = "Guaranteed income from day one! Apply immediately, only 3 seats left today!"
    ids = {d["id"] for d in analyze_indicators(text)}
    assert "C3" in ids


def test_clean_posting_no_critical():
    text = (
        "Senior Software Engineer at Meridian Games Inc, Los Angeles, USA. "
        "You will develop and maintain REST APIs, review pull requests, and mentor engineers. "
        "Requirements: 4+ years with Python, degree preferred. "
        "Base salary range: $120,000 - $150,000 USD. Apply via https://careers.meridiangames.com."
    )
    fired = analyze_indicators(text)
    crit = [d for d in fired if d["severity"] == "Critical"]
    assert crit == []


def test_h1_free_email_with_company():
    text = "Company: Acme Corp. Contact our recruiter at hiring2026@gmail.com for processing."
    ids = {d["id"] for d in analyze_indicators(text)}
    assert "H1" in ids


def test_indicator_shape():
    text = "Pay a registration fee now."
    fired = analyze_indicators(text)
    assert fired
    for d in fired:
        assert set(("id", "name", "severity", "category", "evidence", "explanation")) <= set(d.keys())
        assert d["severity"] in ("Critical", "High", "Medium", "Low")
