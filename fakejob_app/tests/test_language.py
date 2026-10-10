"""Tests for language discipline (risk/language.py)."""

from risk import indicators as ind_mod
from risk.engine import assess_risk
from risk.language import alternative_note, check_language


def test_banned_conclusions_detected():
    assert check_language("This is a scam, do not apply.") != []
    assert check_language("This is fake.") != []
    assert check_language("This is a ghost job.") != []
    assert check_language("This posting is fake!") != []
    assert check_language("") == []
    assert check_language(None) == []


def test_pattern_language_not_banned():
    # Descriptive pattern language must remain usable.
    assert check_language("Fee requests are a classic advance-fee scam pattern.") == []
    assert check_language("High risk of a scam: patterns consistent with fraud.") == []
    assert check_language("Multiple strong indicators suggest elevated risk.") == []


def test_every_indicator_has_alternative():
    for ind_id, _name, _sev, _cat, _fn, _expl in ind_mod.INDICATOR_DEFS:
        note = alternative_note({"id": ind_id, "category": _cat})
        assert note and "could also be explained by" in note, ind_id


def _representative_cases():
    return [
        [],
        [{"id": "L2", "name": "n", "severity": "Low", "category": "Suspicious",
          "evidence": "e", "explanation": "x"}],
        [{"id": "M1", "name": "n", "severity": "Medium", "category": "Suspicious",
          "evidence": "e", "explanation": "x"},
         {"id": "M2", "name": "n", "severity": "Medium", "category": "Suspicious",
          "evidence": "e", "explanation": "x"}],
        [{"id": "H1", "name": "n", "severity": "High", "category": "Scam Indicators",
          "evidence": "e", "explanation": "x"},
         {"id": "H2", "name": "n", "severity": "High", "category": "Scam Indicators",
          "evidence": "e", "explanation": "x"}],
        [{"id": "C1", "name": "Advance fee requested", "severity": "Critical",
          "category": "Scam Indicators",
          "evidence": "all applicants must pay a refundable registration fee",
          "explanation": "x"}],
    ]


def test_all_summaries_clean_and_explained():
    for fired in _representative_cases():
        summary = assess_risk(fired)["summary"]
        assert check_language(summary) == [], summary
        if fired:
            assert "could also be explained by" in summary, summary


def test_all_indicator_explanations_clean():
    for _id, _name, _sev, _cat, _fn, expl in ind_mod.INDICATOR_DEFS:
        assert check_language(expl) == [], _id
