"""
risk/consistency.py
-------------------
Deterministic safety-net checks over a generated risk verdict, in the
spirit of career-ops verify-risk checks. These never weaken a verdict —
they only correct it upward (or repair its wording) when the rules and
the evidence disagree.

Checks:
  V1 critical_floor — a fired Critical indicator with a non-Critical level
       is a contradiction: force Critical and rebuild dependent fields.
  V2 impersonation_pair — free-email (H1) plus domain-mismatch (H4) firing
       together must never sit at Low: raise to at least Medium.
  V3 language_repair — a summary containing banned conclusion phrasing is
       regenerated from the (unchanged) level and indicators.

verify_assessment(fired, assessment) returns (assessment, corrections),
where corrections is a list of applied check ids (empty = clean pass).
"""

from __future__ import annotations

import logging
from typing import Any

from risk import engine as _engine
from risk.language import check_language

logger = logging.getLogger("scam_sentry.consistency")

_LEVEL_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


def _rebuild(fired: list[dict], level: str) -> dict[str, Any]:
    return {
        "overall_risk_level": level,
        "risk_categories": _engine.assign_categories(fired, level),
        "confidence": _engine.assign_confidence(fired, level),
        "summary": _engine.build_summary(level, fired),
        "key_indicators": fired,
    }


def verify_assessment(fired: list[dict] | None,
                      assessment: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply safety-net checks. Returns (assessment, corrections)."""
    fired = fired or []
    ids = {d.get("id") for d in fired}
    level = assessment.get("overall_risk_level", "Low")
    corrections: list[str] = []

    # V1: Critical evidence must always mean a Critical verdict.
    has_critical = any(d.get("severity") == "Critical" for d in fired)
    if has_critical and level != "Critical":
        logger.warning("Consistency V1: Critical indicator fired but level=%s; forcing Critical",
                       level)
        assessment = _rebuild(fired, "Critical")
        level = "Critical"
        corrections.append("V1-critical-floor")

    # V2: H1 + H4 together (free mailbox AND domain mismatch) is a paired
    # impersonation signal that must never stay at Low.
    if "H1" in ids and "H4" in ids and _LEVEL_RANK.get(level, 0) < _LEVEL_RANK["Medium"]:
        logger.warning("Consistency V2: H1+H4 fired but level=%s; raising to Medium", level)
        assessment = _rebuild(fired, "Medium")
        level = "Medium"
        corrections.append("V2-impersonation-pair")

    # V3: banned conclusion phrasing in the summary gets regenerated.
    violations = check_language(assessment.get("summary", ""))
    if violations:
        logger.warning("Consistency V3: banned phrasing in summary; regenerating")
        assessment = dict(assessment)
        assessment["summary"] = _engine.build_summary(level, fired)
        corrections.append("V3-language-repair")

    return assessment, corrections
