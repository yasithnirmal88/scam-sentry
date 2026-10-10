"""
risk/indicators.py
------------------
Severity-graded risk indicators C1-C4, H1-H5, M1-M4, L1-L3.

Each detector is a pure function: (text, metadata) -> (triggered, evidence).
`analyze_indicators` runs all detectors and returns fired indicator dicts:

    {"id", "name", "severity", "category", "evidence", "explanation"}

Language discipline: explanations describe risk patterns, never claim
"This is a scam" / "This is fake".
"""

import re

import fraud_features
from fraud_features import (
    PAYMENT_PATTERNS,
    SENSITIVE_INFO_PATTERNS,
    FREE_EMAIL_DOMAINS,
    URGENCY_PATTERNS,
    UNREALISTIC_BENEFIT_PATTERNS,
    EMAIL_PATTERN,
    URL_PATTERN,
    extract_company_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MARKDOWN_STRIP_RE = re.compile(r"[*_`#]+")

FREE_EMAIL_SET = set(FREE_EMAIL_DOMAINS)

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


def _normalize(text):
    if not text:
        return ""
    return _MARKDOWN_STRIP_RE.sub(" ", text)


def _find_snippet(text, pattern, window=90, flags=re.IGNORECASE):
    """Return a short evidence snippet around the first regex match."""
    if not text:
        return ""
    m = re.search(pattern, text, flags)
    if not m:
        return ""
    start = max(0, m.start() - window // 2)
    end = min(len(text), m.end() + window // 2)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if len(snippet) > 220:
        snippet = snippet[:220].rstrip() + "..."
    return snippet


def _any_match(text, patterns):
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


def _emails(text):
    return EMAIL_PATTERN.findall(text or "")


# ---------------------------------------------------------------------------
# Critical detectors (any one forces Critical)
# ---------------------------------------------------------------------------

def check_c1(text):
    """C1: advance / registration / equipment payment requested."""
    pat = _any_match(text, PAYMENT_PATTERNS)
    if pat:
        return True, _find_snippet(text, pat)
    return False, ""


def check_c2(text):
    """C2: sensitive personal data requested before a formal offer."""
    pat = _any_match(text, SENSITIVE_INFO_PATTERNS)
    if pat:
        return True, _find_snippet(text, pat)
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
    company = extract_company_name(_normalize(text))
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
    company = extract_company_name(_normalize(text))
    if company is None:
        return True, "No clear company / employer name found in the posting"
    if len(company.strip()) <= 2:
        return True, "Company name is extremely short/vague: %s" % company
    return False, ""


def check_h4(text, metadata=None):
    """H4: clear domain mismatch (email domain vs claimed company/website)."""
    text_n = _normalize(text)
    company = extract_company_name(text_n)
    emails = _emails(text)
    urls = URL_PATTERN.findall(text)
    if not emails or not company:
        return False, ""
    simplified = re.sub(r"[^a-z0-9]", "", company.lower())
    if not simplified or len(simplified) < 4:
        return False, ""
    for e in emails:
        domain = e.split("@")[-1].lower().strip(".,;)]")
        if domain in FREE_EMAIL_SET:
            continue
        host = re.sub(r"[^a-z0-9]", "", domain.split(":")[0])
        if simplified[:5] not in host and host[:5] not in simplified:
            return True, "Contact email %s does not match claimed employer %s" % (e, company)
    # Also compare website URLs against claimed company.
    from urllib.parse import urlparse
    for u in urls:
        try:
            host = urlparse(u).netloc.lower()
        except Exception:
            continue
        if not host:
            continue
        clean = re.sub(r"[^a-z0-9]", "", host)
        if simplified[:5] not in clean and clean[:5] not in simplified:
            # Only fire when a company is claimed AND the link looks unrelated.
            if any(k in clean for k in ["verify", "secure", "login", "confirm", "update"]):
                return True, "Link %s looks unrelated to claimed employer %s" % (host, company)
    return False, ""


def check_h5(text):
    """H5: strong ghost / stale signals."""
    pat = _any_match(text, GHOST_PATTERNS)
    if pat:
        return True, _find_snippet(text, pat)
    # Repost + no concrete team/project detail heuristic.
    lowered = (text or "").lower()
    has_team_detail = bool(re.search(r"\bteam\b.{0,40}(of \d+|lead|manager|standup|sprint)", lowered))
    has_project_detail = bool(re.search(r"\bproject\b.{0,40}[a-z]{4,}", lowered))
    if "repost" in lowered and not has_team_detail and not has_project_detail:
        return True, _find_snippet(text, r"repost")
    return False, ""


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
    """M2: no salary range when the market normally expects one."""
    lowered = (text or "").lower()
    has_salary = bool(re.search(r"\b(salary|pay range|compensation|per month|per year|usd|lkr|rs\.?)\b", lowered))
    has_money_number = bool(re.search(r"(\$|usd|lkr|rs\.?)\s?[\d,]{3,}", lowered))
    if not has_salary and not has_money_number:
        # Only meaningful for postings long enough to be expected to state pay.
        if len((text or "").split()) >= 60:
            return True, "No salary range or compensation details mentioned"
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
    has_company = extract_company_name(_normalize(text)) is not None
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
    """L2: benefits not mentioned (often neutral)."""
    lowered = (text or "").lower()
    if len((text or "").split()) >= 80:
        if not re.search(r"\b(benefit|perks|insurance|leave|bonus|allowance|equity|pension)\b", lowered):
            return True, "No benefits or perks mentioned"
    return False, ""


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
    ("M1", "Vague role description", "Medium", "Suspicious", check_m1,
     "The posting lacks concrete responsibilities, team context, or deliverables, making it hard to evaluate."),
    ("M2", "No salary range stated", "Medium", "Suspicious", check_m2,
     "Compensation is missing in a posting long enough that pay would normally be stated. This alone is weak evidence."),
    ("M3", "Unprofessional language", "Medium", "Suspicious", check_m3,
     "Excessive shouting, slang, or pressure phrasing is unusual for professional hiring and merits caution in context."),
    ("M4", "Limited company presence signals", "Medium", "Suspicious", check_m4,
     "A named company with no website, email, or phone provided offers no easy verification path."),
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
    norm = _normalize(text or "")
    fired = []
    for ind_id, name, severity, category, fn, explanation in INDICATOR_DEFS:
        try:
            # Detectors needing metadata accept (text, metadata); others (text,).
            if ind_id in ("H1", "H4"):
                hit, evidence = fn(text or "", metadata)
            else:
                # H3/M4 use normalized-company extraction internally.
                _ = norm
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
    # Deduplicate L3 when H5 already fired (avoid double counting repost).
    ids = {d["id"] for d in fired}
    if "H5" in ids and "L3" in ids:
        fired = [d for d in fired if d["id"] != "L3"]
    return fired
