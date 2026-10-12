"""
fraud_features.py
------------------
Rule / pattern based fraud-indicator extraction for job advertisements.

ROLE: ML-feature support (NOT the authoritative decision layer).
---------------------------------------------------------------
This module exists to (a) feed engineered red-flag features into the ML
classifier alongside TF-IDF text features and (b) provide a transparent
rule-based score/hybrid support signal. It also owns the shared, pure
text-signal primitives (pattern banks, contact/company extraction, and the
company<->domain matcher) that the authoritative Risk Engine reuses.

It is NOT the source of truth for the final verdict. The authoritative risk
decision (overall level, categories, key indicators, actions) is produced by
`risk/indicators.py` + `risk/engine.py`. This module's output may be used as a
NON-AUTHORITATIVE supporting signal (hybrid score / ML feature vector) and
must never override or contradict the Risk Engine's verdict. Where the two
overlap (e.g. company/domain matching) they now share the same helper so they
cannot drift apart.

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


def normalize(text):
    """Strip markdown emphasis markers that break "label: value" parsing.

    Shared by the authoritative Risk Engine (risk/indicators.py) so both
    systems normalize text identically.
    """
    if not text:
        return ""
    return _MARKDOWN_STRIP_RE.sub(" ", text)


# Backwards-compatible private alias (old intra-module name).
_normalize = normalize


# --------------------------------------------------------------------------
# Script / language heuristic
# --------------------------------------------------------------------------

def non_ascii_letter_ratio(text):
    """Return (ratio, n_letters): share of alphabetic chars that are non-ASCII.

    A cheap, deterministic script heuristic. Latin-script English scores ~0.0,
    while Cyrillic/CJK/Arabic/Greek/etc. approaches 1.0; accented Latin
    (é, ü, ñ) contributes a little. Digits, punctuation, and whitespace are
    ignored so formatting never skews the result. Returns (0.0, 0) for input
    with no letters. Used by the Risk Engine to flag content its English-centric
    patterns cannot evaluate reliably (see risk/indicators.py H6).
    """
    if not text:
        return 0.0, 0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0, 0
    n_letters = len(letters)
    non_ascii = sum(1 for c in letters if ord(c) > 127)
    return non_ascii / n_letters, n_letters


# --------------------------------------------------------------------------
# Static keyword / pattern banks
# --------------------------------------------------------------------------
# These are shared by the authoritative Risk Engine (risk/indicators.py) and
# the legacy ML feature detectors below. They cover direct phrasing plus
# common paraphrases ("onboarding fee", "good-faith deposit") and a limited
# set of high-signal non-English equivalents (ES/FR/DE/PT/ID/TL). Wording that
# a legitimate employer could plausibly use descriptively is deliberately kept
# out, or anchored to a request verb, to protect precision.

PAYMENT_PATTERNS = [
    # Direct English fee / deposit phrasing.
    r"registration fee", r"application fee", r"processing fee",
    r"training fee", r"joining fee", r"kit fee", r"uniform fee",
    r"processing charge", r"pay before joining",
    # Paraphrased fee / deposit labels.
    r"(onboarding|orientation|verification|activation|membership|"
    r"admin(?:istrative)?|handling|setup|set-?up|documentation|"
    r"background[- ]?check|good[- ]?faith|caution|interviews?|medical|"
    r"licen[cs]e|courier|delivery|equipment)\s+(fee|charge|deposit|payment)",
    # Qualifier + fee ("a small processing charge", "refundable deposit").
    r"(one[- ]?time|small|nominal|minor|refundable|mandatory|required)\s+"
    r"(fee|charge|deposit|payment)",
    r"(security|good[- ]?faith|caution|admin(?:istrative)?)\s+deposit",
    # Amount / obligation phrasing.
    r"(fee|charge|deposit|payment)\s+of\s+[\$₹€£]?\s*[\d,]+",
    r"(fee|charge|deposit)\s+(is\s+)?(required|mandatory|needed|payable)",
    r"pay\s+(a|an|the|your|some)?\s*"
    r"(fee|charge|deposit|payment|amount|security|caution)",
    r"pay\s+(before|upfront|in advance|to (start|join|begin|proceed))",
    r"(upfront|advance|initial)\s+(payment|fee|deposit|charge)",
    r"refundable\s+(deposit|fee|amount|charge)",
    # Money movement.
    r"send\s+(us\s+)?(money|payment|cash|funds)",
    r"send\s+\$?\s*[\d,]+\s+(to|for|via)",
    r"transfer\s+(the\s+)?(money|amount|fee|funds)",
    r"wire\s+(transfer|the\s+)?(money|funds|amount)",
    r"pay\s+\w*\s*(rs\.?|lkr|usd|inr|\$|₹|€|£)\s*\d",
    r"western union", r"money\s*gram",
    # Spanish.
    r"tarifa\s+de\s+(registro|inscripci[oó]n|activaci[oó]n)",
    r"(cuota|dep[oó]sito)\s+(de\s+)?(registro|inscripci[oó]n|activaci[oó]n)",
    r"pag(o|ar)\s+(por\s+adelantado|anticipad[oa]|inicial)",
    # French.
    r"frais\s+d'?\s*inscription",
    r"frais\s+de\s+(dossier|registre)",
    r"(d[ée]p[oô]t|caution)\s+de\s+(garantie|s[ée]curit[ée])",
    r"paiement\s+(anticip[ée]|à l'avance|initial)",
    # German.
    r"(bearbeitungs|anmelde|registrierungs|verwaltungs|aktivierungs)geb(ü|ue)hr",
    r"es\s+f(ä|ae)llt\s+eine\s+geb(ü|ue)hr",
    r"(kaution|anzahlung)\s+.{0,15}(zahlen|bezahlen|entrichten|erforderlich|verlangt)",
    # Portuguese.
    r"taxa\s+de\s+(inscri[çc][aã]o|registo|registro|ativa[çc][aã]o)",
    r"(dep[oó]sito|cau[çc][aã]o)\s+(reembols[áa]vel|exigid[oa]|necess[áa]ri[oa])",
    r"pagamento\s+(antecipado|inicial)",
    # Indonesian.
    r"biaya\s+(pendaftaran|administrasi|aktivasi|pelatihan)",
    r"deposit\s+(dibutuhkan|diperlukan|wajib)",
    # Filipino / Tagalog.
    r"bayad\s+sa\s+pagpaparehistro",
    r"bayad\s+(muna|bago)",
]

# Request verbs (EN + a few non-English) used to anchor "sensitive data"
# patterns so descriptive uses ("manage account details") do not misfire.
_REQUEST_VERBS = (
    r"(send|share|provide|submit|upload|give|enter|confirm|input|"
    r"enviar|proporciona|comparte|fournir|envoyer|senden|geben|kirim|ibigay)"
)

SENSITIVE_INFO_PATTERNS = [
    # Direct English phrasing.
    r"bank account number", r"account number and", r"passport number",
    r"credit card (number|details)", r"debit card", r"national id\s*(number)?",
    r"nic number", r"social security number", r"\bssn\b",
    r"send (us )?your (bank|card|account|passport|nic)",
    r"\botp\b", r"pin\s*(number|code)", r"\bcvv\b",
    # Request-anchored banking details (paraphrases).
    _REQUEST_VERBS + r"[^.!?]{0,40}\b"
    r"(bank(ing)?\s+(details|information|info|account)|account\s+(details|number)|"
    r"iban|swift code|routing number|sort code|n[úu]mero de cuenta|"
    r"datos bancarios|coordonn[ée]es bancaires|num[ée]ro de compte|"
    r"bankkontonummer|kontodaten|n[úu]mero de conta|dados banc[áa]rios|"
    r"nomor rekening)\b",
    # Request-anchored document copy ("send a copy of your passport/ID").
    _REQUEST_VERBS + r"[^.!?]{0,30}\b"
    r"(copy|photo|scan|picture|front and back)\b[^.!?]{0,15}\b"
    r"(id|passport|nic|national id|driver'?s? licen[cs]e|licen[cs]e|"
    r"pasaporte|passeport|ausweis|identidad)\b",
    # Document term + number/copy ("passport number", "NIC copy").
    r"\b(passport|nic|national id|driver'?s? licen[cs]e|id card)\s+"
    r"(number|copy|photo|scan|details)\b",
]

FREE_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "aol.com", "protonmail.com", "proton.me", "icloud.com", "rediffmail.com",
    "mail.com", "gmx.com", "gmx.net", "yandex.com", "yandex.ru", "zoho.com",
    "tutanota.com", "tuta.io", "fastmail.com", "mail.ru", "163.com", "qq.com",
    "web.de",
]

URGENCY_PATTERNS = [
    r"apply immediately", r"apply now", r"limited positions?",
    r"only \d+ positions?", r"within \d+ hours?", r"last chance",
    r"urgent(ly)? hiring", r"respond immediately", r"act now",
    r"today only", r"hurry", r"immediate joining required",
    r"seats? filling fast",
    # Paraphrased scarcity / pressure.
    r"immediate joining",
    r"positions? (closing|filling)",
    r"limited (slots?|seats?|openings?|vacanc)",
    r"(only|just) \d+ (slots?|seats?|spots?|places?) (left|remain)",
    r"seats? (are )?(filling|going) fast",
    r"time[- ]sensitive",
    r"don'?t (miss out|delay|wait)",
    r"act fast",
    r"last (few|chance)",
    r"closing (soon|today|this week)",
    r"apply (fast|today|asap)",
]

UNREALISTIC_BENEFIT_PATTERNS = [
    r"guaranteed income", r"no experience.{0,15}high salary",
    r"work \d-?\d? hours.{0,20}earn", r"easy money", r"get rich",
    r"unlimited earning", r"100% guaranteed job", r"guaranteed placement",
    r"earn \$?\d+.{0,15}(per day|daily|a day)", r"passive income",
    # Paraphrased income / payout promises.
    r"unlimited (earning|income) potential",
    r"guaranteed (earnings?|payouts?|returns?|profit|weekly pay|daily pay)",
    r"(daily|weekly|instant|same[- ]day)\s+(payouts?|payments?|pay)",
    r"make (money|income)\s+(fast|quickly|daily|from home)",
    r"quick money", r"financial freedom", r"become rich",
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
        # Supporting ML feature. It shares `company_matches_domain` with the
        # authoritative Risk Engine (H4) instead of the old crude 5-char
        # prefix test, so both systems agree on what "unrelated to the
        # company" means and the legacy feature stops contradicting H4.
        keyword_hit = any(k in domain for k in
                           ["verify", "secure-", "login-", "-update", "confirm-"])
        many_hyphens = domain.count("-") >= 2
        company_mismatch = bool(company_name) and not company_matches_domain(
            company_name, domain)
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


# When a labeled value runs into the next field ("Company: Initech LLC.
# Location: Remote"), the header regex over-captures. A sentence boundary
# followed by a known field label almost never belongs to a company name,
# so the value is cut there.
_HEADER_SPILLOVER_RE = re.compile(
    r"\.\s+(Location|Salary|Email|E-?mail|Phone|Contact|Requirements?|"
    r"Responsibilities|Benefits|Apply|Website|Description|Overview|About)\b",
    re.IGNORECASE,
)


def _trim_header_value(value):
    m = _HEADER_SPILLOVER_RE.search(value or "")
    if m:
        value = value[:m.start() + 1]
    return (value or "").strip()


def extract_company_name(text):
    if not text:
        return None
    for p in COMPANY_HEADER_PATTERNS:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return _trim_header_value(m.group(1))

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


# --------------------------------------------------------------------------
# Shared company / domain matching
# --------------------------------------------------------------------------
# Reused by the authoritative Risk Engine (H4 in risk/indicators.py) AND by
# the legacy `detect_suspicious_url` ML feature below, so the two systems
# cannot disagree about whether a contact domain belongs to a claimed
# employer.

# Company-name words that do not identify the entity (legal forms and generic
# descriptors). Stripped before comparing a claimed company to a contact
# domain, so "Acme Solutions Ltd" matches "acmesolutions.com".
COMPANY_GENERIC_WORDS = {
    "inc", "llc", "ltd", "limited", "corporation", "corp", "co", "plc", "pvt",
    "gmbh", "company", "holdings", "group", "partners", "solutions", "services",
    "systems", "technologies", "technology", "global", "international",
    "enterprises", "industries", "ventures", "labs", "studio", "agency",
    "consulting",
}

# Domain labels (TLDs and role-mailbox prefixes) that do not identify an
# organisation and are ignored during matching.
DOMAIN_GENERIC_LABELS = {
    "www", "com", "net", "org", "co", "io", "ai", "app", "dev", "info", "biz",
    "edu", "gov", "uk", "us", "au", "ca", "in", "lk", "mail", "email", "hr",
    "jobs", "job", "careers", "career", "recruit", "recruiting", "apply",
    "contact", "web", "site", "online", "noreply", "no",
}

# Minimum number of shared characters required to call two names related.
_MIN_DOMAIN_MATCH_CHARS = 4


def _alnum_tokens(value):
    """Lowercase alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def company_core_tokens(company):
    """Distinctive words of a company name, dropping legal/generic words."""
    tokens = _alnum_tokens(company)
    core = [t for t in tokens if t not in COMPANY_GENERIC_WORDS]
    if core:
        return core
    # All-generic name (e.g. "Group"): fall back to anything usable.
    return [t for t in tokens if len(t) > 1]


def domain_labels(domain):
    """Meaningful labels of a domain, dropping TLDs / role prefixes."""
    host = (domain or "").lower().split(":")[0]
    labels = [p for p in re.split(r"[^a-z0-9]+", host) if p]
    meaningful = [p for p in labels if p not in DOMAIN_GENERIC_LABELS]
    return meaningful or labels


def longest_common_substring(a, b):
    """Length of the longest shared run of characters in a and b."""
    if not a or not b:
        return 0
    best = 0
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def company_matches_domain(company, domain):
    """Best-effort check that an email/website domain belongs to a company.

    Returns False only on a *clear* mismatch. Short or generic company names
    (and unparseable domains) are treated as inconclusive (True) so the
    heuristic does not misfire on them. Used by both the Risk Engine H4 check
    and the legacy suspicious-url ML feature.
    """
    core = company_core_tokens(company)
    labels = domain_labels(domain)
    if not core or not labels:
        return True
    # Any shared word is a match.
    if set(core) & set(labels):
        return True
    core_join = "".join(core)
    for label in labels:
        if core_join and (core_join in label or label in core_join):
            return True
    # A distinctive name must share a meaningful run of characters.
    if max(len(t) for t in core) < _MIN_DOMAIN_MATCH_CHARS:
        return True  # too short/generic to judge
    for token in core:
        for label in labels:
            if longest_common_substring(token, label) >= _MIN_DOMAIN_MATCH_CHARS:
                return True
    return False


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
