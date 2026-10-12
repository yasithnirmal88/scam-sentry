"""NLP robustness tests for the Risk Engine's text matching.

Covers three improvements that do NOT change the engine's authority:

1. Paraphrase recall — soft/varied wording ("onboarding fee", "good-faith
   deposit", "banking details", "guaranteed weekly payouts") must still fire
   the same graded indicators.
2. Negation discipline — a *negated* fee/credential request ("there is no
   registration fee") must not be read as a Critical scam signal (C1/C2).
3. Light multilingual handling — a limited set of high-signal non-English fee
   phrases fire, and predominantly non-Latin script is flagged (H6) instead of
   returning a misleading confident "Low".

Guarded throughout: real scams stay Critical, clean English stays Low.
"""

import pytest

from fraud_features import detect_free_email, non_ascii_letter_ratio
from risk.engine import assess_risk
from risk.indicators import analyze_indicators


def _ids(text, metadata=None):
    return {d["id"] for d in analyze_indicators(text, metadata)}


def _level(text, metadata=None):
    return assess_risk(analyze_indicators(text, metadata))["overall_risk_level"]


def _mk_ind(ind_id, severity, category="Suspicious"):
    return {"id": ind_id, "name": ind_id, "severity": severity,
            "category": category, "evidence": "some quoted evidence here",
            "explanation": "x"}


CLEAN_ENGLISH = (
    "Senior Data Engineer at Northwind Traders Inc, based in Austin, USA. "
    "You will design data pipelines, build ETL jobs, and mentor analysts on the "
    "platform team. Responsibilities include maintaining our warehouse, "
    "reviewing code, and improving data quality. Requirements: five years of "
    "experience with Python and SQL, strong communication skills, and a "
    "bachelor's degree in computer science. We offer a competitive salary of "
    "120000 USD per year, health benefits, and flexible remote work. Apply "
    "through our careers page at https://northwindtraders.com/careers or email "
    "talent@northwindtraders.com."
)


# ---------------------------------------------------------------------------
# Script heuristic
# ---------------------------------------------------------------------------

def test_non_ascii_letter_ratio_basics():
    assert non_ascii_letter_ratio("Hello world") == (0.0, 10)
    assert non_ascii_letter_ratio("") == (0.0, 0)
    assert non_ascii_letter_ratio("123 !!! ---") == (0.0, 0)
    ratio, letters = non_ascii_letter_ratio("こんにちは")
    assert ratio == 1.0 and letters == 5


# ---------------------------------------------------------------------------
# Paraphrase recall — fees (C1)
# ---------------------------------------------------------------------------

def test_c1_paraphrased_onboarding_fee():
    text = ("A one-time onboarding fee of $30 is required to activate your "
            "worker account before you start.")
    assert "C1" in _ids(text)


def test_c1_paraphrased_good_faith_deposit():
    text = "Candidates must pay a refundable good-faith deposit before the orientation."
    assert "C1" in _ids(text)


def test_c1_paraphrased_processing_charge():
    text = "There is a small processing charge to cover your equipment."
    assert "C1" in _ids(text)


# ---------------------------------------------------------------------------
# Paraphrase recall — sensitive data (C2)
# ---------------------------------------------------------------------------

def test_c2_paraphrased_banking_details():
    text = ("Please share your banking details and a copy of your passport to "
            "finalize onboarding.")
    assert "C2" in _ids(text)


def test_c2_submit_iban_anchor():
    text = "Submit your IBAN and routing number so payroll can set you up."
    assert "C2" in _ids(text)


# ---------------------------------------------------------------------------
# Paraphrase recall — income/pressure (C3), urgency (H2), scam patterns (C4)
# ---------------------------------------------------------------------------

def test_c3_paraphrased_income_and_pressure():
    text = ("Enjoy guaranteed weekly payouts and unlimited earning potential. "
            "Limited seats available, apply fast.")
    assert "C3" in _ids(text)
    assert _level(text) == "Critical"


def test_h2_paraphrased_scarcity():
    assert "H2" in _ids("Limited seats remain. Apply fast, positions are closing soon.")


def test_c4_crypto_wallet_paraphrase():
    text = ("Congratulations, you were selected! Transfer the crypto to our "
            "wallet to activate your position.")
    assert "C4" in _ids(text)


def test_c4_click_to_verify_paraphrase():
    assert "C4" in _ids("Click the link to verify your account and claim your reward.")


# ---------------------------------------------------------------------------
# Negation discipline (C1/C2)
# ---------------------------------------------------------------------------

def test_no_fee_phrasing_does_not_fire_c1():
    for text in (
        "There is no registration fee for this position. We cover all costs.",
        "Candidates never pay any application fee or deposit to us.",
    ):
        assert "C1" not in _ids(text)


def test_negation_guard_does_not_hide_scam_across_clauses():
    # The negation is in a *different* clause from the fee, so C1 must still fire.
    text = "No experience needed. A small registration fee of $20 applies to all hires."
    assert "C1" in _ids(text)


def test_negation_guard_on_sensitive_request():
    text = "We never ask you to send your bank account number before a signed offer."
    assert "C2" not in _ids(text)


# ---------------------------------------------------------------------------
# Light multilingual handling
# ---------------------------------------------------------------------------

def test_detect_free_email_new_providers():
    assert detect_free_email("Email hr@yandex.com")["triggered"] is True
    assert detect_free_email("Email hr@zoho.com")["triggered"] is True
    assert detect_free_email("Email hr@acme.com")["triggered"] is False


def test_h1_free_email_new_provider():
    text = "Company: Northwind Traders\nEmail your resume to hr@yandex.com"
    assert "H1" in _ids(text)


@pytest.mark.parametrize("text", [
    "Se requiere una tarifa de registro de $50 antes de comenzar.",
    "Des frais d'inscription de 50 euros sont exigés avant de commencer.",
    "Für diese Stelle fällt eine Bearbeitungsgebühr an.",
    "Anda harus membayar biaya pendaftaran sebelum mulai kerja.",
])
def test_multilingual_fee_phrases_fire_c1(text):
    assert "C1" in _ids(text)


def test_non_latin_script_flags_h6_and_is_not_low():
    text = ("当社はデータ入力スタッフを募集しています。"
            "応募には登録料が必要です。メールでお問い合わせください。")
    assert "H6" in _ids(text)
    assert _level(text) == "Medium"


def test_h6_does_not_fire_on_accented_english():
    text = ("Café Operations Manager at Northwind Traders, based in Austin, USA. "
            "You will lead the team, manage budgets, and improve service quality. "
            "Requirements include five years of experience and a degree. Apply at "
            "https://northwindtraders.com.")
    assert "H6" not in _ids(text)


# ---------------------------------------------------------------------------
# H6 determination rule (never a confident Low; still not over-escalated)
# ---------------------------------------------------------------------------

def test_h6_alone_forces_at_least_medium():
    assert assess_risk([_mk_ind("H6", "Medium")])["overall_risk_level"] == "Medium"


def test_h6_with_a_single_high_stays_medium():
    fired = [_mk_ind("H3", "High"), _mk_ind("H6", "Medium")]
    assert assess_risk(fired)["overall_risk_level"] == "Medium"


# ---------------------------------------------------------------------------
# Green guards: clean English still Low, hard scams still Critical
# ---------------------------------------------------------------------------

def test_clean_english_stays_low_without_h6():
    assert "H6" not in _ids(CLEAN_ENGLISH)
    assert _level(CLEAN_ENGLISH) == "Low"


def test_paraphrased_advance_fee_is_critical():
    text = ("Work from home data entry. A one-time onboarding fee of $30 is "
            "required before you can start. Limited seats, apply fast.")
    assert _level(text) == "Critical"


def test_onboarding_without_fee_is_not_critical():
    # Wordings that merely *mention* onboarding/orientation must never go Critical.
    fired = analyze_indicators(
        "We provide a full onboarding programme, orientation sessions, and paid "
        "training for every new hire. No prior experience is required.")
    assert not any(d["severity"] == "Critical" for d in fired)
