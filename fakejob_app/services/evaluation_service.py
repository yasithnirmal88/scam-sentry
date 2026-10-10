"""
services/evaluation_service.py
------------------------------
Runs the EXISTING Risk Engine on a job description. No logic rewritten.

Uses app.classify (lazy import to avoid a circular import) so scanned jobs
get the exact same hybrid scores + risk report as paste/upload analysis.
Falls back to the pure rule-based Risk Engine if the ML model is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

import config

logger = logging.getLogger("scam_sentry.evaluation")


def evaluate_text(text: str) -> dict[str, Any]:
    """Full risk result for arbitrary text. Raises ValueError when too short."""
    from app import classify  # deferred: app imports services, not vice versa
    result = classify(text)
    if "error" in result:
        raise ValueError(result["error"])
    return result


def evaluate_job(title: str, company: str, location: str, description: str) -> dict[str, Any]:
    """Risk result for a scanned listing. Falls back to rule-only on ML failure.

    Raises ValueError when there is too little text — callers skip such jobs
    instead of storing a meaningless report.
    """
    combined = "\n".join(p for p in (title, company, location, description) if p)
    if not combined or len(combined.strip()) < config.MIN_TEXT_LENGTH:
        raise ValueError("Not enough text was found to analyse. "
                         "Skipping this listing.")
    try:
        return evaluate_text(combined)
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("ML-backed classify failed (%s); using rule-only risk engine", exc)
        from risk.actions import generate_actions
        from risk.engine import assess_risk
        from risk.indicators import analyze_indicators
        from risk.verification import verify_employer

        fired = analyze_indicators(combined)
        assessment = assess_risk(fired)
        return {
            "overall_risk_level": assessment["overall_risk_level"],
            "risk_categories": assessment["risk_categories"],
            "confidence": assessment["confidence"],
            "summary": assessment["summary"],
            "key_indicators": assessment["key_indicators"],
            "employer_verification": verify_employer(combined, fired),
            "recommended_actions": generate_actions(fired, assessment["overall_risk_level"]),
            "hybrid_score": 0.0,
            "rule_score": 0.0,
            "ml_score": 0.0,
            "raw_text_preview": combined[:800],
        }
