"""Tests for cv_matcher: signal extraction and transparent match scoring."""

import cv_matcher

CV = (
    "Senior Backend Software Engineer\n"
    "Skills: Python, Django, PostgreSQL, Docker, AWS, REST APIs\n"
    "Experience: built data pipelines and REST APIs with Python.\n"
    "Education: BSc Computer Science\n"
)


def _job(jid, title, description, risk="Low", **extra):
    job = {
        "id": jid, "title": title, "company": f"Co{jid}", "location": "",
        "source": "remoteok", "description": description,
        "industry": "Technology & IT", "job_role": "Software Engineer",
        "country": "", "region": "", "overall_risk_level": risk,
    }
    job.update(extra)
    return job


def test_extract_signals_finds_tools_roles_and_sections():
    signals = cv_matcher.extract_signals(CV)
    assert "python" in signals["tools"]
    assert "postgresql" in signals["tools"]
    assert "docker" in signals["tools"]
    assert "Software Engineer" in signals["role_titles"]
    assert "skills" in signals["sections"]
    assert signals["word_count"] > 5
    assert signals["keywords"]


def test_extract_signals_never_raises_on_garbage():
    for garbage in ("", None, 123, "!@#$%", "   "):
        signals = cv_matcher.extract_signals(garbage)
        assert isinstance(signals["skills"], list)
        assert isinstance(signals["tools"], list)
        assert isinstance(signals["role_titles"], list)


def test_matching_ranks_related_job_above_unrelated():
    jobs = [
        _job(1, "Python Backend Engineer",
             "Python Django PostgreSQL Docker AWS REST APIs"),
        _job(2, "Graphic Designer",
             "Photoshop Illustrator branding and visual design"),
    ]
    ranked = cv_matcher.match_jobs(CV, jobs)
    assert ranked[0]["job_id"] == 1
    assert ranked[0]["fit_score"] > ranked[1]["fit_score"]
    assert "python" in ranked[0]["matched_terms"]
    assert "Matches your CV" in ranked[0]["reason"]


def test_expected_result_shape():
    ranked = cv_matcher.match_jobs(CV, [_job(1, "Python Developer", "Python")])
    result = ranked[0]
    assert set(result) >= {
        "job_id", "title", "company", "location", "source", "url", "industry",
        "job_role", "country", "region", "risk_level", "fit_score",
        "matched_terms", "reason",
    }
    assert isinstance(result["fit_score"], int)
    assert "_rank" not in result


def test_match_result_carries_original_url():
    ranked = cv_matcher.match_jobs(
        CV, [_job(1, "Python Developer", "Python",
                  url="https://example.com/jobs/1")])
    assert ranked[0]["url"] == "https://example.com/jobs/1"


def test_critical_jobs_are_not_top_even_with_equal_fit():
    jobs = [
        _job(1, "Python Backend Engineer", "Python Django PostgreSQL Docker AWS",
             risk="Critical"),
        _job(2, "Python Backend Engineer", "Python Django PostgreSQL Docker AWS",
             risk="Low"),
    ]
    ranked = cv_matcher.match_jobs(CV, jobs)
    assert ranked[0]["job_id"] == 2          # safe job first
    assert ranked[0]["risk_level"] == "Low"
    assert ranked[-1]["job_id"] == 1          # critical pushed to the bottom
    assert ranked[-1]["risk_level"] == "Critical"


def test_min_fit_filter_and_limit():
    jobs = [
        _job(1, "Python Backend Engineer", "Python Django PostgreSQL Docker AWS"),
        _job(2, "Graphic Designer", "Photoshop Illustrator branding"),
    ]
    ranked = cv_matcher.match_jobs(CV, jobs, min_fit=50)
    assert [r["job_id"] for r in ranked] == [1]
    assert len(cv_matcher.match_jobs(CV, jobs, limit=1)) == 1


def test_risk_level_and_exclude_risky_filters():
    jobs = [
        _job(1, "Python Engineer", "Python Django", risk="High"),
        _job(2, "Python Engineer", "Python Django", risk="Low"),
        _job(3, "Python Engineer", "Python Django", risk="Critical"),
    ]
    low = cv_matcher.match_jobs(CV, jobs, risk_level="Low")
    assert [r["job_id"] for r in low] == [2]

    safe = cv_matcher.match_jobs(CV, jobs, exclude_risky=True)
    assert {r["job_id"] for r in safe} == {2}


def test_empty_jobs_returns_empty_list():
    assert cv_matcher.match_jobs(CV, []) == []


def test_unrecognized_cv_still_scores_without_error():
    ranked = cv_matcher.match_jobs(
        "just some words about gardening and soil",
        [_job(1, "Python Developer", "Python Django")])
    assert len(ranked) == 1
    assert ranked[0]["fit_score"] >= 0
