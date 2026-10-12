"""
risk/indicators.py
------------------
Severity-graded risk indicators C1-C4, H1-H6, M1-M5, L1-L3.

AUTHORITATIVE RISK DECISIONING. This module (together with risk/engine.py)
is the single source of truth for the final verdict: `analyze_indicators`
produces the fired indicators and `assess_risk` maps them to the overall
risk level, categories, and summary. Nothing else may override it.

`fraud_features.py` complements this module but is NOT authoritative: it
provides ML feature support and a legacy hybrid "supporting signal" only.
Any heuristic shared by the two systems (text normalization, company/domain
matching) lives in `fraud_features.py` and is imported here, so the two can
never drift apart.

Each detector is a pure function: (text, metadata) -> (triggered, evidence).
`analyze_indicators` runs all detectors and returns fired indicator dicts:

    {"id", "name", "severity", "category", "evidence", "explanation"}

Language discipline: explanations describe risk patterns, never claim
"This is a scam" / "This is fake".
"""

import re
from urllib.parse import urlparse

from fraud_features import (
    PAYMENT_PATTERNS,
    SENSITIVE_INFO_PATTERNS,
    FREE_EMAIL_DOMAINS,
    URGENCY_PATTERNS,
    UNREALISTIC_BENEFIT_PATTERNS,
    EMAIL_PATTERN,
    URL_PATTERN,
    extract_company_name,
    # Shared text-signal helpers: single source of truth reused by the legacy
    # ML-feature module so the two systems can't diverge.
    normalize,
    company_matches_domain,
    non_ascii_letter_ratio,
)
from risk.freshness import STALE_DAYS, VERY_STALE_DAYS, job_age_days

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FREE_EMAIL_SET = set(FREE_EMAIL_DOMAINS)

# Matches a free/public mailbox anywhere in text (kept in sync with the single
# FREE_EMAIL_DOMAINS source of truth in fraud_features.py).
_FREE_EMAIL_RX = re.compile(
    r"@(" + "|".join(re.escape(d) for d in FREE_EMAIL_DOMAINS) + r")\b",
    re.IGNORECASE,
)

# Ghost / stale signals: evergreen, always hiring, reposted, no team/project.
GHOST_PATTERNS = [
    r"always hiring",
    r"evergreen (requisition|role|opening)",
    r"multiple openings? (nationwide|across|in all)",
    r"hiring (nationwide|across the country)",
    r"immediate openings? for all",
    r"reposted",
    r"re-?advertised",
    r"ongoing recruitment",
    r"urgently hiring.{0,40}multiple",
]

# Pressure tactics that combine with unrealistic income for C3.
PRESSURE_PATTERNS = [
    r"apply immediately",
    r"apply within \d+ hours?",
    r"only \d+ (positions?|seats?|slots?) left",
    r"last chance",
    r"act now",
    r"today only",
    r"immediate joining required",
    r"respond immediately",
    r"hurry",
    # Paraphrased scarcity / pressure.
    r"act fast",
    r"time[- ]sensitive",
    r"limited (slots?|seats?|openings?|vacanc)",
    r"positions? (closing|filling)",
    r"(only|just) \d+ (slots?|seats?|spots?|places?) (left|remain)",
    r"seats? (are )?(filling|going) fast",
    r"don'?t (miss out|delay|wait)",
    r"closing (soon|today|this week)",
    r"apply (fast|today|asap)",
]

# Confirmed scam patterns: phishing / fake cheque / impersonation / off-platform.
SCAM_PATTERN_LIST = [
    r"fake (check|cheque)",
    r"cash the (check|cheque)",
    r"money mule",
    r"wire (the )?(funds|money) (back|on)",
    r"send.{0,30}via (western union|moneygram|gift card|steam card|itunes card)",
    r"whatsapp.{0,40}(verification|activation|code)",
    r"telegram.{0,20}@",
    r"claim your (spot|bonus|reward)",
    r"verify your account.{0,30}(link|urgent)",
    r"login.{0,20}to (claim|verify|confirm)",
    r"impersonat",
    r"on behalf of.{0,30}(without|no).{0,20}authori",
    # Paraphrased known-scam phrasing.
    r"(crypto|bitcoin|btc|usdt|wallet)\b.{0,30}\b(send|transfer|deposit|payment|address)",
    r"\b(send|transfer|deposit)\b.{0,25}\b(crypto|bitcoin|btc|usdt|wallet)\b",
    r"click\b.{0,25}\b(here|link)\b.{0,25}\b(verify|confirm|claim|activate|receive)",
    r"congratulations\b.{0,40}\b(selected|chosen|winner|won)",
    r"use your (bank )?account to (receive|deposit|transfer|hold)",
    r"(keep|take)\s+(your|a)\s+(cut|commission)\b.{0,40}\b(transfer|send|wire|forward)",
]

# Vague role: absence of responsibility / qualification signal words.
ROLE_SPECIFIC_PATTERNS = [
    r"\bresponsib", r"\bqualifications?\b", r"\brequirements?\b",
    r"\bduties\b", r"\bdeliverables?\b", r"\bteam\b", r"\byears? of experience\b",
    r"\bdegree\b", r"\bcertifi", r"\bskills?\b",
]

# Unprofessional language heuristics.
PROFANITY_SLOP_PATTERNS = [
    r"\b(!!!+|\?\?\?+)",
    r"\b[a-z]+\b.{0,5}\b[a-z]+\b.{0,5}(dm me|inbox me|pm me)",
    r"\bno interview\b",
    r"\bno resume required\b",
]

LOWERCASE_SHOUT_RE = re.compile(r"[A-Z\s!]{40,}")
EXCLAMATION_RE = re.compile(r"!{3,}")


def _snippet_from_match(text, m, window=90):
    """Return a short evidence snippet around a regex match object."""
    if m is None or not text:
        return ""
    start = max(0, m.start() - window // 2)
    end = min(len(text), m.end() + window // 2)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if len(snippet) > 220:
        snippet = snippet[:220].rstrip() + "..."
    return snippet


def _find_snippet(text, pattern, window=90, flags=re.IGNORECASE):
    """Return a short evidence snippet around the first regex match."""
    if not text:
        return ""
    return _snippet_from_match(text, re.search(pattern, text, flags), window)


def _any_match(text, patterns):
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


# Clause boundaries + negation words used to suppress false Critical hits on a
# *negated* fee/credential request ("there is no registration fee", "we never
# ask for your bank details"). Applied to C1/C2 only: negation-aware matching
# is intentionally conservative so the other detectors cannot silently lose
# real signals.
_CLAUSE_SPLIT_RE = re.compile(r"[,;.!?\n]")
_NEGATION_RE = re.compile(
    r"\b(no|not|never|without|free of|zero|none|"
    r"kein(e|en|er)?|ohne|sans|sin|sem|tanpa|nunca|não|nao)\b",
    re.IGNORECASE,
)
NEGATION_WINDOW = 40


def _clause_start(text, idx):
    """Index of the token that opens the clause containing idx."""
    start = 0
    for m in _CLAUSE_SPLIT_RE.finditer(text, 0, idx):
        start = m.end()
    return start


def _match_negation_aware(text, patterns):
    """First pattern match that is not negated within its own clause.

    Returns (pattern, match) or (None, None). A match is skipped when a
    negation word sits within NEGATION_WINDOW characters before it in the same
    clause, so "there is no registration fee" does not fire while "no
    experience needed. The registration fee is $50" still does.
    """
    if not text:
        return None, None
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            clause_start = _clause_start(text, m.start())
            prefix_start = max(clause_start, m.start() - NEGATION_WINDOW)
            if _NEGATION_RE.search(text[prefix_start:m.start()]):
                continue
            return p, m
    return None, None


def _emails(text):
    return EMAIL_PATTERN.findall(text or "")


# ---------------------------------------------------------------------------
# Critical detectors (any one forces Critical)
# ---------------------------------------------------------------------------

def check_c1(text):
    """C1: advance / registration / equipment payment requested."""
    pat, m = _match_negation_aware(text, PAYMENT_PATTERNS)
    if pat:
        return True, _snippet_from_match(text, m)
    return False, ""


def check_c2(text):
    """C2: sensitive personal data requested before a formal offer."""
    pat, m = _match_negation_aware(text, SENSITIVE_INFO_PATTERNS)
    if pat:
        return True, _snippet_from_match(text, m)
    return False, ""


def check_c3(text):
    """C3: guaranteed unrealistic income + pressure tactics."""
    income_pat = _any_match(text, UNREALISTIC_BENEFIT_PATTERNS)
    pressure_pat = _any_match(text, PRESSURE_PATTERNS)
    if income_pat and pressure_pat:
        return True, _find_snippet(text, income_pat)
    # Very explicit guarantee phrasing also qualifies alone.
    strong = _any_match(text, [r"guaranteed income", r"100% guaranteed job",
                               r"guaranteed placement", r"guaranteed instant income"])
    if strong:
        return True, _find_snippet(text, strong)
    return False, ""


def check_c4(text):
    """C4: confirmed scam patterns (phishing, fake cheques, impersonation)."""
    pat = _any_match(text, SCAM_PATTERN_LIST)
    if pat:
        return True, _find_snippet(text, pat)
    return False, ""


# ---------------------------------------------------------------------------
# High detectors
# ---------------------------------------------------------------------------

def check_h1(text, metadata=None):
    """H1: free email domain while claiming to represent a company."""
    emails = _emails(text)
    company = extract_company_name(normalize(text))
    for e in emails:
        try:
            domain = e.split("@")[-1].lower().strip(".,;)]")
        except Exception:
            continue
        if domain in FREE_EMAIL_SET and company:
            return True, "Contact %s (free domain) for claimed employer %s" % (e, company)
    return False, ""


def check_h2(text):
    """H2: strong urgency language."""
    pat = _any_match(text, URGENCY_PATTERNS + PRESSURE_PATTERNS)
    if pat:
        return True, _find_snippet(text, pat)
    return False, ""


def check_h3(text):
    """H3: missing or extremely vague company information."""
    company = extract_company_name(normalize(text))
    if company is None:
        return True, "No clear company / employer name found in the posting"
    if len(company.strip()) <= 2:
        return True, "Company name is extremely short/vague: %s" % company
    return False, ""


def check_h4(text, metadata=None):
    """H4: contact domain that clearly does not match the claimed employer.

    Uses the shared company/domain matcher (fraud_features) so the Risk Engine
    and the legacy ML feature agree on what counts as a mismatch.
    """
    company = extract_company_name(normalize(text))
    emails = _emails(text)
    urls = URL_PATTERN.findall(text)
    if not company or (not emails and not urls):
        return False, ""
    for e in emails:
        domain = e.split("@")[-1].lower().strip(".,;)]")
        if domain in FREE_EMAIL_SET:
            continue
        if not company_matches_domain(company, domain):
            return True, "Contact %s does not match claimed employer %s" % (e, company)
    # A link that both looks like an impersonation page and does not match the
    # claimed employer is also a mismatch signal.
    for url in urls:
        host = urlparse(url).netloc.lower()
        if not host:
            continue
        if re.search(r"verify|secure|login|log-?in|update|confirm|account", host) \
                and not company_matches_domain(company, host):
            return True, "Link %s does not match claimed employer %s" % (host, company)
    return False, ""


def _freshness_context(metadata):
    """Return (age_days, evergreen_pat_or_None) for stale-signal detectors."""
    metadata = metadata or {}
    try:
        age = job_age_days(metadata.get("posted_at"), now=metadata.get("now"))
    except Exception:
        age = None
    return age


def check_h5(text, metadata=None):
    """H5: strong ghost / stale signals (wording and/or posting age)."""
    pat = _any_match(text, GHOST_PATTERNS)
    age = _freshness_context(metadata)
    if pat:
        evidence = _find_snippet(text, pat)
        if age is not None and age > STALE_DAYS:
            evidence = "%s [posted ~%d days ago]" % (evidence, age)
        return True, evidence
    # Very old postings are strong stale signals even without evergreen wording.
    if age is not None and age > VERY_STALE_DAYS:
        return True, "Posted ~%d days ago — well beyond a typical hiring window" % age
    # Old + evergreen-leaning repost without concrete detail.
    lowered = (text or "").lower()
    has_team_detail = bool(re.search(r"\bteam\b.{0,40}(of \d+|lead|manager|standup|sprint)", lowered))
    has_project_detail = bool(re.search(r"\bproject\b.{0,40}[a-z]{4,}", lowered))
    if "repost" in lowered and not has_team_detail and not has_project_detail:
        return True, _find_snippet(text, r"repost")
    return False, ""


def check_h6(text):
    """H6: predominantly non-English / non-Latin script content.

    The Engine and its pattern banks are English-centric, so a non-Latin-script
    or heavily mixed-language posting cannot be evaluated reliably. Rather than
    emit a confident "low risk" — which really means "found nothing in text we
    cannot parse" — the language gap is reported so the verdict is honest about
    the limits of the analysis. This is not evidence of fraud (severity Medium),
    just a confidence caveat. Deterministic; no model involved.
    """
    ratio, n_letters = non_ascii_letter_ratio(text or "")
    if n_letters >= 20 and ratio >= 0.30:
        sample = re.sub(r"\s+", " ", (text or "").strip())[:120]
        return True, ("Text appears predominantly non-English / non-Latin script "
                      "(%.0f%% non-ASCII letters); automated analysis is "
                      "English-centric. Sample: %s" % (ratio * 100, sample))
    return False, ""


# Concrete start-date / timeline language. Its absence supports (but never
# alone triggers) the M5 aging signal.
TIMELINE_PATTERNS = [
    r"\bstart(ing)? (date|immediately|asap|in \w+)",
    r"\bjoin(ing)? (us |our team |in \w+|by )",
    r"\btimeline\b", r"\bstart date\b",
    r"\bq[1-4]\b", r"\b20\d\d\b",
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
]


def _has_timeline(text):
    return _any_match(text or "", TIMELINE_PATTERNS) is not None


def check_m5(text, metadata=None):
    """M5: possibly stale posting (aging listing, weaker than H5)."""
    age = _freshness_context(metadata)
    if age is None:
        return False, ""
    if age <= STALE_DAYS or age > VERY_STALE_DAYS:
        # Fresh listings are fine; very old ones belong to H5 instead.
        return False, ""
    evidence = "Posted ~%d days ago" % age
    if not _has_timeline(text):
        evidence += "; no start date or timeline mentioned"
    return True, evidence


# ---------------------------------------------------------------------------
# Medium detectors
# ---------------------------------------------------------------------------

def check_m1(text):
    """M1: vague role description (no responsibilities/team/deliverables)."""
    lowered = (text or "").lower()
    hits = sum(1 for p in ROLE_SPECIFIC_PATTERNS if re.search(p, lowered))
    words = len((text or "").split())
    if hits <= 1 and words >= 40:
        snippet = re.sub(r"\s+", " ", (text or "")[:200]).strip()
        return True, snippet
    return False, ""


def check_m2(text):
    """M2: no salary stated, only where the omission is notable in context.

    A missing salary is extremely common in legitimate ads, so it is reported
    only when the posting ALSO shows a context where stated pay would be
    notable: urgency/pressure, a free-mailbox contact, explicit "no experience
    / high pay" bait, or unprofessional phrasing. On an otherwise clean,
    detailed post the omission stays silent.
    """
    lowered = (text or "").lower()
    has_salary = bool(re.search(
        r"\b(salary|pay range|compensation|per month|per year|usd|lkr|rs\.?)\b", lowered))
    has_money_number = bool(re.search(r"(\$|usd|lkr|rs\.?)\s?[\d,]{3,}", lowered))
    if has_salary or has_money_number:
        return False, ""
    # Too short to expect stated pay.
    if len((text or "").split()) < 60:
        return False, ""
    suspicious_context = (
        _any_match(text, URGENCY_PATTERNS + PRESSURE_PATTERNS) is not None
        or bool(_FREE_EMAIL_RX.search(lowered))
        or bool(re.search(
            r"no experience|anyone can (apply|join)|no interview|no resume", lowered))
        or _any_match(text, [r"earn \$?\d+", r"high salary", r"per day", r"daily pay"]) is not None
    )
    if suspicious_context:
        return True, ("No salary range or compensation mentioned alongside "
                      "other pressure or non-professional signals")
    return False, ""


def check_m3(text):
    """M3: unprofessional language / poor grammar (context-dependent)."""
    if EXCLAMATION_RE.search(text or ""):
        return True, _find_snippet(text, r"!{3,}")
    pat = _any_match(text or "", PROFANITY_SLOP_PATTERNS)
    if pat:
        return True, _find_snippet(text, pat)
    # ALL-CAPS shouting blocks.
    m = LOWERCASE_SHOUT_RE.search(text or "")
    if m and len(m.group(0)) >= 60:
        snippet = re.sub(r"\s+", " ", m.group(0)[:160]).strip()
        return True, snippet
    return False, ""


def check_m4(text):
    """M4: limited company online presence signals (no website/contact)."""
    lowered = (text or "").lower()
    has_url = bool(URL_PATTERN.search(text or ""))
    has_email = bool(EMAIL_PATTERN.search(text or ""))
    has_phone = bool(re.search(r"\+?\d[\d\s\-()]{7,}\d", text or ""))
    has_company = extract_company_name(normalize(text)) is not None
    if has_company and not has_url and not has_email and not has_phone:
        return True, "Company is named but no website, email, or phone is provided"
    _ = lowered
    return False, ""


# ---------------------------------------------------------------------------
# Low detectors
# ---------------------------------------------------------------------------

def check_l1(text):
    """L1: minor title / responsibilities mismatch (weak heuristic)."""
    lowered = (text or "").lower()
    title_m = re.search(r"(job title|title|role|position)\s*:\s*([a-z /&\-]{3,60})", lowered)
    if title_m:
        title = title_m.group(2)
        # e.g. senior title but only generic duties mentioned.
        if "senior" in title or "lead" in title or "manager" in title:
            hits = sum(1 for p in ROLE_SPECIFIC_PATTERNS if re.search(p, lowered))
            if hits <= 2:
                return True, "Senior-sounding title with only generic duties described"
    return False, ""


def check_l2(text):
    """L2: benefits not mentioned — low impact and only in context.

    Absence of benefits is normal in many ads, so it is noted only when the
    post is long AND already states compensation (a detailed, otherwise
    professional post that quotes pay but omits benefits). Low severity: it is
    never enough on its own to raise the overall level.
    """
    lowered = (text or "").lower()
    if len((text or "").split()) < 80:
        return False, ""
    if re.search(r"\b(benefit|perks|insurance|leave|bonus|allowance|equity|pension)\b", lowered):
        return False, ""
    has_salary = bool(re.search(
        r"\b(salary|pay range|compensation|per month|per year|usd|lkr|rs\.?)\b", lowered)) \
        or bool(re.search(r"(\$|usd|lkr|rs\.?)\s?[\d,]{3,}", lowered))
    if not has_salary:
        return False, ""
    return True, "No benefits or perks mentioned despite stated compensation"


def check_l3(text):
    """L3: single repost (only meaningful with other signals)."""
    if re.search(r"\brepost(ed)?\b", (text or ""), re.IGNORECASE):
        # Only count as low if H5 did not already fire strongly.
        h5_hit, _ = check_h5(text)
        if not h5_hit:
            return True, _find_snippet(text, r"repost(ed)?")
    return False, ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

INDICATOR_DEFS = [
    # id, name, severity, category, check_fn, explanation
    ("C1", "Advance fee requested", "Critical", "Scam Indicators", check_c1,
     "Legitimate employers do not ask candidates to pay registration, training, or equipment fees. Fee requests are a classic advance-fee scam pattern."),
    ("C2", "Sensitive personal data requested", "Critical", "Scam Indicators", check_c2,
     "Requests for bank details, national ID, passport, or card data before a formal offer are strong scam indicators. Legitimate hiring collects these only late in a verified process."),
    ("C3", "Guaranteed unrealistic income plus pressure", "Critical", "Scam Indicators", check_c3,
     "Promises of guaranteed high income combined with pressure to act fast are consistent with fraudulent postings."),
    ("C4", "Confirmed scam pattern", "Critical", "Scam Indicators", check_c4,
     "The text matches known scam phrasing such as fake-cheque schemes, phishing verification, or impersonation language."),
    ("H1", "Free email for claimed company", "High", "Scam Indicators", check_h1,
     "A recruiter claiming to represent an established company but using a free mailbox is a common impersonation signal."),
    ("H2", "Strong urgency language", "High", "Scam Indicators", check_h2,
     "Extreme urgency is often used to rush decisions before the candidate can verify the employer."),
    ("H3", "Missing or vague company information", "High", "Suspicious", check_h3,
     "Postings with no identifiable employer are harder to verify and merit caution."),
    ("H4", "Email/domain mismatch", "High", "Scam Indicators", check_h4,
     "The contact email or link domain does not match the claimed employer, which suggests possible impersonation."),
    ("H5", "Ghost / stale signals", "High", "Ghost/Stale", check_h5,
     "Evergreen or repeatedly reposted wording with no concrete team or project detail can indicate a stale or non-genuine listing."),
    ("H6", "Non-English / mixed-language content", "Medium", "Suspicious", check_h6,
     "The posting is written largely in a non-Latin script or a language the English-centric rules cannot fully evaluate. This limits confidence and is not itself evidence of fraud."),
    ("M1", "Vague role description", "Medium", "Suspicious", check_m1,
     "The posting lacks concrete responsibilities, team context, or deliverables, making it hard to evaluate."),
    ("M2", "No salary range stated", "Medium", "Suspicious", check_m2,
     "Compensation is missing in a posting that also shows other weak or pressure signals. Absence of pay alone is weak evidence."),
    ("M3", "Unprofessional language", "Medium", "Suspicious", check_m3,
     "Excessive shouting, slang, or pressure phrasing is unusual for professional hiring and merits caution in context."),
    ("M4", "Limited company presence signals", "Medium", "Suspicious", check_m4,
     "A named company with no website, email, or phone provided offers no easy verification path."),
    ("M5", "Possibly stale posting", "Medium", "Ghost/Stale", check_m5,
     "The listing is aging past a typical hiring window, so the role may no longer be active. Age alone proves nothing — confirm before applying."),
    ("L1", "Title / duties mismatch", "Low", "Suspicious", check_l1,
     "Minor mismatch between a senior-sounding title and generic duties. Weak signal on its own."),
    ("L2", "Benefits not mentioned", "Low", "Suspicious", check_l2,
     "Benefits are not mentioned. This is often neutral and only meaningful alongside other signals."),
    ("L3", "Single repost", "Low", "Ghost/Stale", check_l3,
     "A single repost mention. Only meaningful together with other ghost or suspicious signals."),
]


def analyze_indicators(text, metadata=None):
    """Run all detectors. Returns list of fired indicator dicts."""
    metadata = metadata or {}
    fired = []
    for ind_id, name, severity, category, fn, explanation in INDICATOR_DEFS:
        try:
            # Detectors needing metadata accept (text, metadata); others (text,).
            if ind_id in ("H1", "H4", "H5", "M5"):
                hit, evidence = fn(text or "", metadata)
            else:
                hit, evidence = fn(text or "")
        except Exception:
            hit, evidence = False, ""
        if hit:
            fired.append({
                "id": ind_id,
                "name": name,
                "severity": severity,
                "category": category,
                "evidence": (evidence or "")[:280],
                "explanation": explanation,
            })
    # Strongest first: Critical > High > Medium > Low.
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    fired.sort(key=lambda d: (order.get(d["severity"], 4), d["id"]))
    # Deduplicate age/repost signals when H5 already fired (avoid double
    # counting the same staleness evidence at lower severities).
    ids = {d["id"] for d in fired}
    if "H5" in ids:
        fired = [d for d in fired if d["id"] not in ("L3", "M5")]
    return fired
