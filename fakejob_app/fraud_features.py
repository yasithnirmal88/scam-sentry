"""
fraud_features.py
------------------
Rule / pattern based fraud-indicator extraction for job advertisements.

Rather than letting the ML model discover fraud patterns purely from
word associations (which can accidentally learn "assistant" -> fake,
"developer" -> genuine simply because of dataset imbalance), this
module explicitly detects the real-world red flags that recruitment
fraud researchers and job-safety guides describe. These engineered
features are:

  1. Fed into the ML classifier alongside TF-IDF text features.
  2. Used directly to build a transparent, rule-based risk score.
  3. Used to generate the human-readable "Detected Risk Indicators"
     explanation shown to the user (replacing raw SHAP word dumps
     such as "assistant" / "skill" with meaningful evidence).

Every detector returns a dict: {"triggered": bool, "detail": str}
"""

import re
from urllib.parse import urlparse

# --------------------------------------------------------------------------
# Markdown / formatting normalization
# --------------------------------------------------------------------------
# Users frequently paste ads that have been through a markdown renderer
# (e.g. "**Company:** Prime Business Group"). The literal ** / __ / backtick
# characters sit between the label and the value and were silently breaking
# every "label: value" regex below, causing correctly-labeled company and
# location fields to be reported as "missing". Strip markdown emphasis
# markers before any pattern matching so labeled fields are found reliably.
_MARKDOWN_STRIP_RE = re.compile(r"[*_`#]+")


def _normalize(text):
    if not text:
        return ""
    return _MARKDOWN_STRIP_RE.sub(" ", text)


# --------------------------------------------------------------------------
# Static keyword / pattern banks
# --------------------------------------------------------------------------

PAYMENT_PATTERNS = [
    r"registration fee", r"application fee", r"processing fee",
    r"training fee", r"pay before joining", r"refundable deposit",
    r"security deposit", r"deposit required", r"payment required",
    r"send money", r"western union", r"money\s*gram", r"pay\s+(a|an|the)?\s*fee",
    r"upfront payment", r"pay\s+\w*\s*(rs\.?|lkr|usd|\$)\s*\d",
    r"processing charge", r"joining fee", r"kit fee", r"uniform fee",
]

SENSITIVE_INFO_PATTERNS = [
    r"bank account number", r"account number and", r"passport number",
    r"credit card (number|details)", r"debit card", r"national id\s*(number)?",
    r"nic number", r"social security number", r"ssn\b",
    r"send (us )?your (bank|card|account|passport|nic)", r"otp\b",
    r"pin\s*(number|code)", r"cvv",
]

FREE_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "aol.com", "protonmail.com", "icloud.com", "rediffmail.com", "mail.com",
]

URGENCY_PATTERNS = [
    r"apply immediately", r"apply now", r"limited positions?",
    r"only \d+ positions?", r"within \d+ hours?", r"last chance",
    r"urgent(ly)? hiring", r"respond immediately", r"act now",
    r"today only", r"hurry", r"immediate joining required",
    r"seats? filling fast",
]

UNREALISTIC_BENEFIT_PATTERNS = [
    r"guaranteed income", r"no experience.{0,15}high salary",
    r"work \d-?\d? hours.{0,20}earn", r"easy money", r"get rich",
    r"unlimited earning", r"100% guaranteed job", r"guaranteed placement",
    r"earn \$?\d+.{0,15}(per day|daily|a day)", r"passive income",
]

GENERIC_PHRASES = [
    "passionate individual", "amazing team", "exciting projects",
    "great opportunity", "dynamic environment", "fast-paced environment",
    "self starter", "go getter", "think outside the box",
    "wear many hats", "rockstar", "ninja", "guru",
]

SPECIFIC_INDICATORS = [
    r"\bpython\b", r"\bjava\b", r"\bsql\b", r"\breact\b", r"\bexcel\b",
    r"\bapi\b", r"\bdegree\b", r"\byears? of experience\b", r"\bresponsib",
    r"\bqualifications?\b", r"\brequirements?\b", r"\bcertifi",
    r"\bmicrosoft office\b", r"\bcommunication skills\b", r"\bdeadline",
    r"\bproject\b", r"\bbenefits?\b", r"\bsalary\b", r"\blocation\b",
]

COMPANY_HEADER_PATTERNS = [
    r"company\s*:\s*([A-Za-z0-9 &.,\-]{2,60})",
    r"employer\s*:\s*([A-Za-z0-9 &.,\-]{2,60})",
    r"organi[sz]ation\s*:\s*([A-Za-z0-9 &.,\-]{2,60})",
]

# Fallback patterns for real-world postings that name the company in prose
# rather than a labeled "Company:" field (e.g. "As a Software Engineer at
# Riot, ..." or "...members of Riot Games, Inc.").
COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&',\.]*(?:\s+[A-Z][A-Za-z0-9&',\.]*){0,3}\s+"
    r"(?:Inc|LLC|Ltd|Limited|Corporation|Corp|Co|plc|GmbH)\.?)\b"
)
AT_COMPANY_PATTERN = re.compile(
    r"\bat ([A-Z][A-Za-z0-9&\'\.]{1,30}(?:\s+[A-Z][A-Za-z0-9&\'\.]{1,30}){0,2})[,.\s]"
)
COMMON_CAPITALIZED_SKIP = set("""
I We You Your The A An This That These Those Our Us They He She It
Job Location Additional Locations Responsibilities Requirements
Qualifications Required Desired Perks Benefits Summary Overview About
Apply Application Team Teams Us Company Employer Location Salary Base
""".split())

LOCATION_PATTERNS = [
    r"location\s*:\s*([A-Za-z0-9 ,.\-]{2,60})",
    r"based in", r"office (is |will be )?located",
]

# Fallback: a bare "City, Country/State" line, common in real postings
# (e.g. "Los Angeles, USA", "London, UK", "Toronto, Canada", "Remote").
LOCATION_FALLBACK_PATTERN = re.compile(
    r"\b[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?,\s*"
    r"(USA|United States|U\.S\.|US|UK|United Kingdom|Canada|Australia|"
    r"Germany|France|Ireland|Singapore|India|China|Japan|Philippines|"
    r"Poland|Spain|Brazil|Mexico|Sri Lanka|[A-Z]{2})\b"
)
REMOTE_PATTERN = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b", re.IGNORECASE)

SALARY_PATTERN = re.compile(
    r"(rs\.?|lkr|usd|\$|inr)?\s?([\d,]{4,10})\s*(per month|/month|monthly|p\.?m\.?)?",
    re.IGNORECASE,
)

NO_EXPERIENCE_PATTERN = re.compile(
    r"no (?:prior |previous |work |formal )?experience (?:is )?(required|needed|necessary)|"
    r"no experience necessary|"
    r"fresh(er)?s? welcome|"
    r"entry.?level.{0,20}no experience|"
    r"no degree (?:is )?required|"
    r"no qualifications? (?:are )?(required|needed)|"
    r"anyone can (apply|join)",
    re.IGNORECASE,
)

URL_PATTERN = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9\-.]+")


def _any_pattern(text_lower, patterns):
    for p in patterns:
        if re.search(p, text_lower, re.IGNORECASE):
            return True
    return False


def detect_payment_request(text):
    hit = _any_pattern(text, PAYMENT_PATTERNS)
    return {
        "key": "payment_request",
        "label": "Payment Request",
        "triggered": hit,
        "severity": "HIGH",
        "detail": ("The advertisement asks the applicant to pay a fee, "
                   "deposit, or send money before or during the hiring "
                   "process.") if hit else None,
    }


def detect_sensitive_information(text):
    hit = _any_pattern(text, SENSITIVE_INFO_PATTERNS)
    return {
        "key": "sensitive_information",
        "label": "Sensitive Information Request",
        "triggered": hit,
        "severity": "HIGH",
        "detail": ("The advertisement requests banking, identity, or "
                   "other sensitive personal information up front.") if hit else None,
    }


def detect_free_email(text):
    emails = EMAIL_PATTERN.findall(text)
    domain_hit = None
    for e in emails:
        domain = e.split("@")[-1].lower()
        if domain in FREE_EMAIL_DOMAINS:
            domain_hit = domain
            break
    return {
        "key": "free_email",
        "label": "Free Email Provider",
        "triggered": domain_hit is not None,
        "severity": "MEDIUM",
        "detail": (f"The recruiter contact uses a free/public email domain "
                   f"({domain_hit}) instead of an official company domain.") if domain_hit else None,
        "domain": domain_hit,
    }


def detect_urgency(text):
    hit = _any_pattern(text, URGENCY_PATTERNS)
    return {
        "key": "urgency",
        "label": "Urgency / Pressure Language",
        "triggered": hit,
        "severity": "LOW",
        "detail": ("The advertisement uses high-pressure or urgency "
                   "language to rush the applicant's decision.") if hit else None,
    }


def detect_unrealistic_benefits(text):
    hit = _any_pattern(text, UNREALISTIC_BENEFIT_PATTERNS)
    return {
        "key": "unrealistic_benefits",
        "label": "Unrealistic Benefits / Earnings Claims",
        "triggered": hit,
        "severity": "MEDIUM",
        "detail": ("The advertisement makes unusually strong guarantees "
                   "about income or job placement.") if hit else None,
    }


def detect_suspicious_url(text, company_name=None):
    urls = URL_PATTERN.findall(text)
    suspicious = None
    for u in urls:
        try:
            domain = urlparse(u).netloc.lower()
        except Exception:
            continue
        if not domain:
            continue
        # crude heuristics: many hyphens, suspicious keywords, or
        # domain unrelated to company name
        keyword_hit = any(k in domain for k in
                           ["verify", "secure-", "login-", "-update", "confirm-"])
        many_hyphens = domain.count("-") >= 2
        company_mismatch = False
        if company_name:
            simplified = re.sub(r"[^a-z0-9]", "", company_name.lower())
            if simplified and simplified[:5] not in domain.replace("-", ""):
                company_mismatch = True
        if keyword_hit or many_hyphens or company_mismatch:
            suspicious = domain
            break
    return {
        "key": "suspicious_url",
        "label": "Suspicious Link",
        "triggered": suspicious is not None,
        "severity": "HIGH",
        "detail": (f"A link in the advertisement ({suspicious}) looks "
                   f"unrelated to the company or uses suspicious wording.") if suspicious else None,
    }


def detect_missing_company(text):
    missing = extract_company_name(text) is None
    return {
        "key": "company_missing",
        "label": "Missing Company Information",
        "triggered": missing,
        "severity": "MEDIUM",
        "detail": ("No clear company / employer name could be found in "
                   "the advertisement.") if missing else None,
    }


def detect_missing_location(text):
    hit = _any_pattern(text, LOCATION_PATTERNS)
    if not hit:
        hit = bool(LOCATION_FALLBACK_PATTERN.search(text)) or bool(REMOTE_PATTERN.search(text))
    missing = not hit
    return {
        "key": "location_missing",
        "label": "Missing Work Location",
        "triggered": missing,
        "severity": "LOW",
        "detail": ("No work location or office address is mentioned.") if missing else None,
    }


def detect_high_salary_no_experience(text):
    no_exp = bool(NO_EXPERIENCE_PATTERN.search(text))
    salary_hit = False
    max_salary = 0
    for m in SALARY_PATTERN.finditer(text):
        num = m.group(2)
        if not num:
            continue
        try:
            val = int(num.replace(",", ""))
        except ValueError:
            continue
        if val > max_salary:
            max_salary = val
    # Heuristic threshold tuned for LKR monthly salary context used in the
    # proposal's example; still generically useful as "very high number
    # attached to a role with no experience required".
    if no_exp and max_salary >= 150000:
        salary_hit = True
    return {
        "key": "high_salary_no_experience",
        "label": "High Salary With No Experience Required",
        "triggered": salary_hit,
        "severity": "HIGH",
        "detail": (f"An unusually high salary (~{max_salary:,}) is offered "
                   f"for a role that explicitly requires no experience.") if salary_hit else None,
    }


def detect_generic_description(text):
    text_lower = text.lower()
    generic_hits = sum(1 for p in GENERIC_PHRASES if p in text_lower)
    specific_hits = sum(1 for p in SPECIFIC_INDICATORS if re.search(p, text_lower))
    word_count = len(text.split())
    # Short, buzzword-heavy, low specific-detail postings are a signal.
    is_generic = (specific_hits <= 2 and word_count < 120) or (generic_hits >= 3 and specific_hits <= 3)
    return {
        "key": "generic_description",
        "label": "Vague / Generic Job Description",
        "triggered": is_generic,
        "severity": "MEDIUM",
        "detail": ("The description lacks concrete responsibilities, "
                   "required skills, or qualifications and relies mostly "
                   "on generic buzzwords.") if is_generic else None,
        "specific_hits": specific_hits,
        "generic_hits": generic_hits,
        "word_count": word_count,
    }


def extract_company_name(text):
    for p in COMPANY_HEADER_PATTERNS:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    m = AT_COMPANY_PATTERN.search(text)
    if m:
        candidate = m.group(1).strip()
        if candidate not in COMMON_CAPITALIZED_SKIP:
            return candidate

    m = COMPANY_SUFFIX_PATTERN.search(text)
    if m:
        return m.group(1).strip()

    # Fallback: the most frequently repeated capitalized word that isn't a
    # generic heading/pronoun is very likely the company/product name in
    # prose-style postings that never use a "Company:" label at all.
    words = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text)
    counts = {}
    for w in words:
        if w in COMMON_CAPITALIZED_SKIP:
            continue
        counts[w] = counts.get(w, 0) + 1
    if counts:
        best, freq = max(counts.items(), key=lambda kv: kv[1])
        if freq >= 3:
            return best

    return None


# Severity -> risk weight used for the transparent rule-based score.
SEVERITY_WEIGHTS = {"HIGH": 22, "MEDIUM": 12, "LOW": 6}

# Indicators that are, on their own, decisive real-world scam behavior.
# A rule engine that only ever nudges a weighted average can be out-voted
# by the ML side even when one of these fires alone (e.g. a request for a
# bank account number). extract_all_features() applies a score floor when
# any of these trigger so a single strong piece of evidence can't be
# diluted away - see CRITICAL_SCORE_FLOOR below and its use in app.py.
CRITICAL_KEYS = {"payment_request", "sensitive_information"}
CRITICAL_SCORE_FLOOR = 70

# Strong evidence that carries a bit more false-positive risk on its own
# (a domain-name heuristic can misfire on legitimate but unusually-named
# sites), so it gets a lower floor than CRITICAL_KEYS - enough to
# guarantee at least a Fake / MEDIUM-risk verdict rather than letting the
# ML side average it away to "Genuine".
STRONG_KEYS = {"suspicious_url"}
STRONG_SCORE_FLOOR = 60


def extract_all_features(text):
    """
    Run every detector over the given text and return:
      - features: dict of key -> 0/1 (for the ML feature vector)
      - indicators: list of triggered indicator dicts (for explanation UI)
      - rule_score: 0-100 transparent risk score
      - critical_hit: True if a decisive indicator (payment / sensitive
        info request) triggered on its own
    """
    text = _normalize(text)
    company = extract_company_name(text)
    detectors = [
        detect_payment_request(text),
        detect_sensitive_information(text),
        detect_free_email(text),
        detect_urgency(text),
        detect_unrealistic_benefits(text),
        detect_suspicious_url(text, company),
        detect_missing_company(text),
        detect_missing_location(text),
        detect_high_salary_no_experience(text),
        detect_generic_description(text),
    ]

    features = {d["key"]: int(bool(d["triggered"])) for d in detectors}
    indicators = [d for d in detectors if d["triggered"]]
    # Sort strongest evidence first
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    indicators.sort(key=lambda d: order.get(d["severity"], 3))

    raw_score = sum(SEVERITY_WEIGHTS[d["severity"]] for d in indicators)
    rule_score = min(100, raw_score)
    critical_hit = any(features.get(k) for k in CRITICAL_KEYS)
    strong_hit = any(features.get(k) for k in STRONG_KEYS)

    return {
        "features": features,
        "indicators": indicators,
        "rule_score": rule_score,
        "company_detected": company,
        "critical_hit": critical_hit,
        "strong_hit": strong_hit,
    }


FEATURE_KEYS = [
    "payment_request", "sensitive_information", "free_email", "urgency",
    "unrealistic_benefits", "suspicious_url", "company_missing",
    "location_missing", "high_salary_no_experience", "generic_description",
]


def features_to_vector(features_dict):
    """Stable-ordered numeric vector for the ML model."""
    return [features_dict.get(k, 0) for k in FEATURE_KEYS]
