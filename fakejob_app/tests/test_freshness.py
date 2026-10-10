"""Tests for lightweight freshness/liveness signals (risk/freshness.py + H5/M5)."""

from datetime import datetime, timedelta, timezone

from risk.engine import assess_risk
from risk.freshness import (freshness_band, freshness_status, job_age_days,
                            parse_posted_at)
from risk.indicators import analyze_indicators
from risk.language import check_language


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


CLEAN_TEXT = (
    "Senior Software Engineer at Meridian Games Inc, Los Angeles, USA. "
    "You will develop and maintain REST APIs, review pull requests, and mentor engineers. "
    "Requirements: 4+ years with Python, degree preferred. Start date flexible in Q3. "
    "Benefits include health insurance and equity. "
    "Base salary range: $120,000 - $150,000 USD. "
    "Apply via https://careers.meridiangames.com or email jobs@meridiangames.com."
)

EVERGREEN_TEXT = (
    "Customer Support Representative at Bright Path Recruiters. "
    "We are always hiring support agents nationwide. Ongoing recruitment with "
    "applications reviewed on a rolling basis. No experience needed, apply today."
)


# --- parsing ---

def test_parse_iso_and_z():
    assert parse_posted_at("2026-01-15") is not None
    assert parse_posted_at("2026-01-15T10:00:00Z") is not None
    assert parse_posted_at("2026-10-09T18:42:49+00:00") is not None


def test_parse_epoch_and_garbage():
    assert parse_posted_at(1791600009) is not None
    assert parse_posted_at("1791600009") is not None
    assert parse_posted_at("not a date") is None
    assert parse_posted_at("") is None
    assert parse_posted_at(None) is None
    assert parse_posted_at(object()) is None


def test_age_and_bands():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert job_age_days("2026-10-05", now=now) == 5
    assert job_age_days(None, now=now) is None
    assert freshness_band(5) == "fresh"
    assert freshness_band(61) == "stale"
    assert freshness_band(91) == "very_stale"
    assert freshness_band(None) == "unknown"


def test_future_dates_clamp_to_zero():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert job_age_days("2026-12-01", now=now) == 0


def test_liveness_note():
    assert freshness_status(_days_ago(5), False)["liveness"] == "likely-active"
    assert freshness_status(_days_ago(100), False)["liveness"] == "possibly-stale"
    assert freshness_status(None, True)["liveness"] == "possibly-stale"
    assert freshness_status(None, False)["liveness"] == "unknown"


# --- indicators ---

def test_recent_clean_job_has_no_freshness_fire():
    fired = analyze_indicators(CLEAN_TEXT, {"posted_at": _days_ago(5)})
    assert {d["id"] for d in fired} == set()


def test_very_old_clean_text_fires_h5():
    fired = analyze_indicators(CLEAN_TEXT, {"posted_at": _days_ago(120)})
    ids = {d["id"] for d in fired}
    assert "H5" in ids and "M5" not in ids  # no double counting
    h5 = next(d for d in fired if d["id"] == "H5")
    assert "120" in h5["evidence"] or "days ago" in h5["evidence"]


def test_aging_band_fires_m5_not_h5():
    fired = analyze_indicators(CLEAN_TEXT, {"posted_at": _days_ago(70)})
    ids = {d["id"] for d in fired}
    assert "M5" in ids and "H5" not in ids
    assert assess_risk(fired)["overall_risk_level"] == "Low"  # single Medium


def test_missing_date_never_crashes_nor_fires():
    for meta in (None, {}, {"posted_at": None}, {"posted_at": "garbage"}):
        fired = analyze_indicators(CLEAN_TEXT, meta)
        assert all(d["id"] not in ("H5", "M5") for d in fired)


def test_old_evergreen_fires_h5_with_age_note():
    fired = analyze_indicators(EVERGREEN_TEXT, {"posted_at": _days_ago(70)})
    assert "H5" in {d["id"] for d in fired}


def test_freshness_never_overrides_critical():
    scam = ("Pay a refundable registration fee of $50. Send bank details. "
            "Apply immediately! Contact x@gmail.com. Company: Global Data Ltd. "
            "Develop software and maintain systems with the team.")
    fired = analyze_indicators(scam, {"posted_at": _days_ago(200)})
    result = assess_risk(fired)
    assert result["overall_risk_level"] == "Critical"
    assert any(d["severity"] == "Critical" for d in result["key_indicators"])


# --- output ---

def test_ghost_summary_mentions_staleness_carefully():
    fired = analyze_indicators(CLEAN_TEXT, {"posted_at": _days_ago(70)})
    summary = assess_risk(fired)["summary"]
    assert "possibly outdated listing" in summary
    assert check_language(summary) == []


def test_m5_brings_confirm_active_action():
    from risk.actions import generate_actions
    fired = analyze_indicators(CLEAN_TEXT, {"posted_at": _days_ago(70)})
    actions = generate_actions(fired, "Low")
    assert any("still active" in a for a in actions)


def test_posted_at_flows_through_evaluate_job():
    from services.evaluation_service import evaluate_job
    result = evaluate_job("Senior Engineer", "Meridian Games Inc",
                          "Los Angeles, USA", CLEAN_TEXT, posted_at=_days_ago(120))
    assert "error" not in result
    assert "H5" in {k["id"] for k in result["key_indicators"]}
