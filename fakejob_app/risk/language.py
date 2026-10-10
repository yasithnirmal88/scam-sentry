"""
risk/language.py
----------------
Language discipline for the Risk Assessment layer (career-ops style).

Signals and risk levels are reported; absolute verdicts are never stated.
This module owns:
  - BANNED_CONCLUSIONS: conclusion phrasing that must never appear in
    user-facing output ("this is a scam", "this is fake", ...).
  - check_language(text): deterministic sweep returning any violations.
  - alternative_note(indicator): a "could also be explained by" line so
    every summary allows a legitimate explanation where one is plausible.
"""

from __future__ import annotations

import re

# Conclusion-style claims. Pattern-describing language elsewhere
# ("scam pattern", "fraud indicator") is intentionally NOT banned.
BANNED_CONCLUSIONS = [
    r"\bthis is a scam\b",
    r"\bthis is fake\b",
    r"\bthis posting is a scam\b",
    r"\bthis posting is fake\b",
    r"\bthis job is a scam\b",
    r"\bthis job is fake\b",
    r"\bthis is a ghost job\b",
    r"\bthis is a ghost posting\b",
    r"\bdefinitely a scam\b",
    r"\bdefinitely fake\b",
    r"\bconfirmed to be a scam\b",
    r"\b100%\s*(a\s*)?(scam|fake)\b",
    r"\bproven (scam|fake)\b",
]

_BANNED_RES = [re.compile(p, re.IGNORECASE) for p in BANNED_CONCLUSIONS]


def check_language(text: str | None) -> list[str]:
    """Return the banned conclusion phrases found in text (empty = clean)."""
    if not text:
        return []
    return [p.pattern for p in _BANNED_RES if p.search(text)]


# Legitimate alternative explanations, keyed by indicator id. These keep
# summaries honest: a signal is evidence, not proof.
_ALTERNATIVES = {
    "C1": "this could also be explained by a poorly worded reimbursement policy — ask for it in writing before paying anything",
    "C2": "this could also be explained by a premature but legitimate onboarding form — insist on a verified offer first",
    "C3": "this could also be explained by aggressive sales-style marketing — ask for verifiable pay records",
    "C4": "this could also be explained by copied boilerplate — verify every contact channel independently",
    "H1": "this could also be explained by a small business or startup without its own mail domain — verify the company another way",
    "H2": "this could also be explained by a genuinely urgent hiring need — urgency alone proves nothing",
    "H3": "this could also be explained by a confidential search or an incomplete posting — ask who the employer is",
    "H4": "this could also be explained by outsourcing or a rebrand — confirm the relationship on the official site",
    "H5": "this could also be explained by high-turnover roles that are always open — confirm the role is currently active",
    "M1": "this could also be explained by a short-form posting — ask for the full role description",
    "M2": "this could also be explained by a negotiable or variable package — ask for the range in writing",
    "M3": "this could also be explained by a non-native author or hasty drafting — weigh it only with other signals",
    "M4": "this could also be explained by a new or stealth company — look for any independent trace of it",
    "M5": "this could also be explained by a slow hiring process or a re-advertised role — confirm it is still open",
    "L1": "this could also be explained by a loosely written title — clarify the actual duties",
    "L2": "this could also be explained by a minimal posting format — ask about benefits directly",
    "L3": "this could also be explained by routine re-advertising — confirm the role is still open",
}

_FALLBACK_ALTERNATIVES = {
    "Scam Indicators": "these patterns could also have innocent explanations — verify each one before deciding",
    "Ghost/Stale": "this could also be explained by routine re-advertising — confirm the role is still active",
    "Suspicious": "these points could also be explained by a hastily written posting — ask for clarification",
    "Likely Genuine": "no system is perfect — a short verification pass is still worthwhile",
}


def alternative_note(indicator: dict | None) -> str:
    """One careful 'could also be explained by' sentence fragment."""
    if not indicator:
        return _FALLBACK_ALTERNATIVES["Likely Genuine"]
    note = _ALTERNATIVES.get(indicator.get("id", ""))
    if note:
        return note
    return _FALLBACK_ALTERNATIVES.get(indicator.get("category", ""),
                                      _FALLBACK_ALTERNATIVES["Suspicious"])
