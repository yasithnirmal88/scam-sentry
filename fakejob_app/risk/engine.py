"""
risk/engine.py
--------------
Determination rules (first match wins), categories, confidence, summary.

Rules (exact order):
  1. Any Critical -> Critical
  2. >= 2 High -> High
  3. 1 High + >= 2 Medium -> High
  4. 1 High alone -> Medium
  5. >= 2 Medium -> Medium
  6. H5 alone -> Medium
  7. Only Low or none -> Low

Confidence reflects evidence strength, not the level:
  High   -> multiple strong/direct indicators agree
  Medium -> some indicators present but evidence is partial
  Low    -> few indicators or weak/ambiguous evidence
  (No indicators at all caps at Medium: absence of evidence is
  reassuring but never proof.)

Language discipline enforced (see risk/language.py): summaries speak in
risk levels and evidence with room for legitimate explanations — never
"This is a scam" / "This is fake" / "This is a ghost job".
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from risk.language import alternative_note

logger = logging.getLogger("scam_sentry.risk_engine")

# A snippet this long is treated as a direct quote of the offending text
# rather than a vague or synthetic note.
DIRECT_EVIDENCE_MIN_CHARS = 20


def _counts(fired):
    c = Counter()
    for d in fired:
        c[d.get("severity", "")] += 1
    return c


def determine_level(fired):
    """Apply determination rules in order. Returns Critical/High/Medium/Low."""
    ids = {d.get("id") for d in (fired or [])}
    sev = _counts(fired or [])
    n_high = sev.get("High", 0)
    n_medium = sev.get("Medium", 0)

    # 1. Any Critical -> Critical
    if sev.get("Critical", 0) >= 1:
        return "Critical"
    # 2. >= 2 High -> High
    if n_high >= 2:
        return "High"
    # 3. 1 High + >= 2 Medium -> High
    if n_high == 1 and n_medium >= 2:
        return "High"
    # 4. 1 High alone -> Medium
    if n_high == 1:
        return "Medium"
    # 5. >= 2 Medium -> Medium
    if n_medium >= 2:
        return "Medium"
    # 6. H5 alone -> Medium
    if ids == {"H5"}:
        return "Medium"
    # 7. Only Low or none -> Low
    return "Low"


def has_critical(fired) -> bool:
    """True when any Critical-severity indicator fired.

    Used by callers (e.g. the hybrid score floor in app.classify) so the
    score floor and the verdict logic stay aligned on the same evidence.
    """
    return any(d.get("severity") == "Critical" for d in (fired or []))


def evidence_is_direct(indicator: dict | None) -> bool:
    """True when the indicator carries a substantive quoted snippet."""
    if not indicator:
        return False
    evidence = (indicator.get("evidence") or "").strip()
    return len(evidence) >= DIRECT_EVIDENCE_MIN_CHARS


def _strong_count(fired) -> int:
    return sum(1 for d in (fired or []) if d.get("severity") in ("Critical", "High"))


def assign_categories(fired, level):
    """Multi-label categories. Returns list of strings."""
    cats = set()
    for d in fired or []:
        cat = d.get("category")
        if cat in ("Scam Indicators", "Ghost/Stale", "Suspicious"):
            cats.add(cat)
    if not fired:
        return ["Likely Genuine"]
    if level == "Low" and not cats:
        return ["Likely Genuine"]
    # Low risk with only weak signals can still be Likely Genuine + Suspicious.
    ordered = [c for c in ("Scam Indicators", "Ghost/Stale", "Suspicious", "Likely Genuine") if c in cats]
    if level == "Low" and len(fired) <= 1:
        # Keep weak-signal nuance: e.g. only L2 -> Suspicious + Likely Genuine?
        # Spec allows multiple categories; keep it simple: include Likely Genuine
        # only when no Scam/Ghost categories fired.
        if "Scam Indicators" not in cats and "Ghost/Stale" not in cats:
            ordered.append("Likely Genuine")
    return ordered or ["Likely Genuine"]


def assign_confidence(fired, level):
    """Confidence from evidence strength (see module docstring)."""
    fired = fired or []
    n_crit = sum(1 for d in fired if d.get("severity") == "Critical")
    n_high = sum(1 for d in fired if d.get("severity") == "High")
    n_med = sum(1 for d in fired if d.get("severity") == "Medium")
    strong = n_crit + n_high

    # High: multiple strong/direct indicators agree.
    if strong >= 2:
        return "High"
    if n_crit == 1 and any(evidence_is_direct(d) for d in fired
                           if d.get("severity") == "Critical"):
        return "High"
    if not fired:
        return "Medium"  # reassuring, but absence of evidence is not proof
    # Medium: some indicators present but evidence is partial.
    if strong == 1 or n_med >= 2:
        return "Medium"
    # Low: few indicators or weak/ambiguous evidence only.
    return "Low"


def _ghost_ids(fired):
    return [d.get("id") for d in (fired or []) if d.get("id") in ("H5", "M5", "L3")]


def _staleness_clause(fired):
    """Careful staleness mention for ghost-signal verdicts (empty when N/A)."""
    ghost = _ghost_ids(fired)
    if not ghost:
        return ""
    return (" This posting also shows patterns consistent with a possibly "
            "outdated listing — confirm the role is still active before applying.")


def build_summary(level, fired):
    """Careful 1-3 sentence summary with strict language discipline."""
    fired = fired or []
    if not fired:
        return ("This posting shows patterns consistent with genuine listings — "
                "no major fraud or ghost indicators were found. "
                "Standard verification is still advised, as no screening is perfect.")
    top = fired[0] if fired else {}
    top_id = top.get("id", "?")
    top_name = top.get("name") or top_id
    n = len(fired)
    alt = alternative_note(top)
    others = (" In total, %d indicators were found." % n) if n > 1 else ""
    stale = _staleness_clause(fired)
    if level == "Critical":
        return ("High risk of a scam: this posting shows patterns consistent with "
                "high-risk fraud (%s: %s).%s%s "
                "Treat it as critical risk — do not send money or sensitive data; "
                "note that %s."
                % (top_id, top_name, others, stale, alt))
    if level == "High":
        return ("Multiple strong indicators suggest elevated risk "
                "(strongest: %s).%s%s "
                "Verify the employer carefully before engaging; %s."
                % (top_name, others, stale, alt))
    if level == "Medium":
        return ("This posting shows some patterns consistent with suspicious listings "
                "(%s).%s "
                "Proceed with caution and verify the employer before sharing personal "
                "details; %s."
                % (top_name, stale, alt))
    return ("This posting shows only weak or isolated signals (%s), which suggests "
            "low risk.%s "
            "A light verification pass is still sensible; %s."
            % (top_name, stale, alt))


def assess_risk(fired):
    """Full risk assessment from fired indicators, plus safety-net checks."""
    from risk.consistency import verify_assessment  # deferred: avoids import cycle

    fired = fired or []
    level = determine_level(fired)
    assessment: dict[str, Any] = {
        "overall_risk_level": level,
        "risk_categories": assign_categories(fired, level),
        "confidence": assign_confidence(fired, level),
        "summary": build_summary(level, fired),
        "key_indicators": fired,
    }
    assessment, corrections = verify_assessment(fired, assessment)
    assessment["corrections"] = corrections
    if corrections:
        logger.warning("Risk consistency checks applied: %s", corrections)
    return assessment
