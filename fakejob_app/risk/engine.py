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

Language discipline enforced: summaries speak in risk levels and evidence,
never "this is a scam" / "this is fake".
"""

from collections import Counter


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
    """High/Medium/Low confidence."""
    n_crit = sum(1 for d in (fired or []) if d.get("severity") == "Critical")
    n_high = sum(1 for d in (fired or []) if d.get("severity") == "High")
    n_med = sum(1 for d in (fired or []) if d.get("severity") == "Medium")
    total = len(fired or [])

    if level == "Critical":
        return "High" if n_crit >= 1 and (n_high + n_med >= 1 or n_crit >= 2) else "Medium" if n_crit >= 1 else "Low"
    if level == "High":
        return "High" if n_high >= 2 else "Medium"
    if level == "Medium":
        if n_high >= 1 or n_med >= 2:
            return "Medium"
        return "Low"
    # Low
    if total == 0:
        return "Medium"  # confident there is nothing alarming
    return "Low"


def build_summary(level, fired):
    """Careful 1-2 sentence summary with language discipline."""
    if not fired:
        return ("This posting shows no major fraud or ghost indicators. "
                "It reads consistently with a genuine listing, but standard verification is still advised.")
    top = fired[0]
    n = len(fired)
    if level == "Critical":
        return ("This posting shows patterns consistent with high-risk scams "
                "(%s: %s). Treat it as critical risk and do not send money or sensitive data."
                % (top["id"], top["name"]))
    if level == "High":
        return ("Multiple strong warning signs were found (%d indicators, strongest: %s). "
                "This posting carries high risk and needs careful verification before engaging."
                % (n, top["name"]))
    if level == "Medium":
        return ("Some suspicious characteristics were found (%s%s). "
                "Proceed with caution and verify the employer before sharing personal details."
                % (top["name"], (" plus %d more" % (n - 1)) if n > 1 else ""))
    return ("Only weak or isolated signals were found%s. "
            "Risk appears low, but light verification is still sensible."
            % ((" (%s)" % top["name"]) if fired else ""))


def assess_risk(fired):
    """Full risk assessment from fired indicators."""
    fired = fired or []
    level = determine_level(fired)
    return {
        "overall_risk_level": level,
        "risk_categories": assign_categories(fired, level),
        "confidence": assign_confidence(fired, level),
        "summary": build_summary(level, fired),
        "key_indicators": fired,
    }
