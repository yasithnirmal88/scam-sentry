"""Precision-focused tests for the Risk Engine.

Covers the softened weak indicators (M2 no-salary, L2 no-benefits, H4
company/domain mismatch) and the determination-rule sensitivity around weak
Medium indicators — while guarding that real scams still go Critical.
"""

from risk.engine import assess_risk
from risk.indicators import analyze_indicators, check_h4, check_l2, check_m2


def _mk(ind_id, severity="Medium", category="Suspicious"):
    return {"id": ind_id, "name": ind_id, "severity": severity,
            "category": category, "evidence": "e", "explanation": "x"}


def _ids(text, metadata=None):
    return {d["id"] for d in analyze_indicators(text, metadata)}


def _level(text, metadata=None):
    return assess_risk(analyze_indicators(text, metadata))["overall_risk_level"]


# ---------------------------------------------------------------------------
# Sample postings
# ---------------------------------------------------------------------------

# Clean, detailed, professional posting that simply omits salary.
CLEAN_NO_SALARY = (
    "Senior Backend Engineer at Northwind Traders Inc, based in Austin, USA. "
    "You will design and maintain REST APIs, review pull requests, and mentor "
    "engineers across the platform team. Day to day responsibilities include "
    "system design, improving developer tooling, and supporting an on-call "
    "rotation. Requirements: five years of experience with Python and "
    "PostgreSQL, strong communication skills, and a bachelor's degree in "
    "computer science or equivalent. We value collaboration and clear "
    "documentation. Apply through our careers page at "
    "https://northwindtraders.com/careers or email talent@northwindtraders.com."
)

# Clean, detailed posting that states salary but never mentions benefits.
CLEAN_NO_BENEFITS = (
    "Data Analyst position at Contoso Ltd, based in Austin, USA. The successful "
    "candidate will design dashboards, write SQL queries, clean datasets, and "
    "present findings to senior stakeholders across the business. Day to day "
    "responsibilities include maintaining reporting pipelines, documenting data "
    "definitions, and partnering with product managers to define metrics. "
    "Requirements include three or more years of experience in analytics, "
    "strong Excel and Python skills, excellent communication, and a degree in "
    "a quantitative field. The salary for this role is 85000 USD per year and "
    "the position is fully remote. To apply, send your resume through our "
    "website at https://contoso.com/jobs or email hr@contoso.com."
)

# Long, sparse posting with no stated pay and no benefits.
LONG_NO_PAY_NO_BENEFITS = (
    "We are a company that values hard work. We are looking for a motivated "
    "person to join a growing team and help with various tasks as needed. "
    "The right candidate is a self starter who enjoys a fast paced environment "
    "and is willing to wear many hats. You will work with other team members, "
    "support daily operations, and help keep things running smoothly. We offer "
    "a great opportunity in a dynamic environment and pride ourselves on being "
    "a fun place to work. If you are a rockstar who thinks outside the box, we "
    "would love to hear from you. This role reports to a team lead and involves "
    "a variety of general duties that change from week to week. Please send "
    "your details if you are interested in joining our growing organisation."
)

ADVANCE_FEE_SCAM = (
    "Work from home data entry assistants wanted. A refundable registration fee "
    "of $50 is required before you can start. Limited positions, apply "
    "immediately! Contact the recruiter to reserve your seat today."
)

SENSITIVE_DATA_SCAM = (
    "To confirm your slot, send your bank account number, national ID number, "
    "and a copy of your passport to our recruitment team today."
)


# ---------------------------------------------------------------------------
# M2 — no salary (contextual)
# ---------------------------------------------------------------------------

def test_m2_silent_on_clean_post_without_salary():
    assert len(CLEAN_NO_SALARY.split()) >= 60  # would have tripped the old M2
    assert check_m2(CLEAN_NO_SALARY)[0] is False


def test_m2_fires_only_with_context():
    pressured = (
        "Urgent: data entry workers needed nationwide. Apply immediately, only a "
        "few seats left. No experience needed and no interview required. You will "
        "update spreadsheets, reply to emails, and support the team with daily "
        "administrative tasks such as data cleaning, data entry, record keeping, "
        "and basic reporting. Selected candidates receive full training and "
        "ongoing support from a supervisor. To get started, send your name and "
        "phone number to quickjobs99@gmail.com and a coordinator will contact you."
    )
    assert len(pressured.split()) >= 60
    assert check_m2(pressured)[0] is True


# ---------------------------------------------------------------------------
# L2 — benefits (contextual, always low impact)
# ---------------------------------------------------------------------------

def test_l2_requires_stated_compensation():
    assert len(LONG_NO_PAY_NO_BENEFITS.split()) >= 80
    # Long post with no stated pay -> the omission is not about benefits.
    assert check_l2(LONG_NO_PAY_NO_BENEFITS)[0] is False
    # Long post that states pay but omits benefits -> fires.
    assert check_l2(CLEAN_NO_BENEFITS)[0] is True


def test_l2_alone_stays_low():
    assert _level(CLEAN_NO_BENEFITS) == "Low"
    assert "L2" in _ids(CLEAN_NO_BENEFITS)


# ---------------------------------------------------------------------------
# H4 — company / domain mismatch (true + false positives)
# ---------------------------------------------------------------------------

def test_h4_fires_on_clear_domain_mismatch():
    text = ("Join Acme Corporation as a Software Engineer. "
            "Send your application to careers@totally-unrelated-verify.com.")
    assert check_h4(text)[0] is True


def test_h4_fires_on_impersonation_link():
    text = ("Company: Acme Corporation. Apply through our portal at "
            "https://secure-login-verify-account.example.com/apply.")
    assert check_h4(text)[0] is True


def test_h4_ignores_matching_domain():
    assert check_h4("Company: Globex Inc. Email hr@globex.com.")[0] is False


def test_h4_ignores_generic_suffix_domain():
    # "Solutions"/"Ltd" are generic; the core "acme" still matches.
    assert check_h4("Company: Acme Solutions Ltd. Email hr@acmesolutions.com.")[0] is False


def test_h4_ignores_subdomain_contact():
    assert check_h4("Company: Wayve. Apply via jobs@careers.wayve.ai.")[0] is False


def test_h4_ignores_too_short_company_name():
    # A 3-character name is too short/generic to call a mismatch on.
    assert check_h4("Company: ABC. Email jobs@xyzcorp.com.")[0] is False


def test_h4_does_not_fire_without_company_or_email():
    assert check_h4("Email hr@somewhere.com with no company named.")[0] is False
    assert check_h4("Company: Acme Corp, apply on our website.")[0] is False


# ---------------------------------------------------------------------------
# Determination rules — weak Medium accumulation
# ---------------------------------------------------------------------------

def test_two_weak_mediums_stay_low():
    fired = [_mk("M2"), _mk("M4")]
    assert assess_risk(fired)["overall_risk_level"] == "Low"


def test_substantive_plus_weak_medium_is_medium():
    fired = [_mk("M1"), _mk("M2")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


def test_three_weak_like_mediums_is_medium():
    fired = [_mk("M2"), _mk("M4"), _mk("M1")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


# ---------------------------------------------------------------------------
# End-to-end: precision without losing recall
# ---------------------------------------------------------------------------

def test_clean_no_salary_stays_low():
    assert _level(CLEAN_NO_SALARY) == "Low"
    assert "M2" not in _ids(CLEAN_NO_SALARY)


def test_clean_no_benefits_stays_low():
    assert _level(CLEAN_NO_BENEFITS) == "Low"


def test_sparse_post_missing_company_stays_medium_not_critical():
    # No real company information is a genuine High signal (H3); it must still
    # stop at Medium, and must not be dragged to Critical by weak signals.
    assert "H3" in _ids(LONG_NO_PAY_NO_BENEFITS)
    assert _level(LONG_NO_PAY_NO_BENEFITS) == "Medium"


def test_advance_fee_scam_stays_critical():
    assert "C1" in _ids(ADVANCE_FEE_SCAM)
    assert _level(ADVANCE_FEE_SCAM) == "Critical"


def test_sensitive_data_scam_stays_critical():
    assert "C2" in _ids(SENSITIVE_DATA_SCAM)
    assert _level(SENSITIVE_DATA_SCAM) == "Critical"
