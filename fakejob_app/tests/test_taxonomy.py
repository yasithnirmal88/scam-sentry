"""Tests for taxonomy: world industry/role classification + picker data."""

from taxonomy import (
    INDUSTRIES, INDUSTRIES_LIST, classify, roles_for_industry,
)


def test_known_role_classifications():
    assert classify("Senior Software Engineer") == ("Technology & IT", "Software Engineer")
    assert classify("Registered Nurse - ICU") == ("Healthcare", "Registered Nurse")
    assert classify("Front Desk Agent") == ("Hospitality & Tourism", "Front Desk Agent")
    assert classify("Data Scientist II") == ("Technology & IT", "Data Scientist")
    assert classify("Construction Project Manager") == (
        "Engineering & Construction", "Construction Project Manager")
    assert classify("Project Manager") == ("Technology & IT", "Product Manager")
    assert classify("Financial Analyst") == ("Finance & Banking", "Financial Analyst")
    assert classify("Customer Support Agent") == ("Customer Service", "Customer Support Agent")
    assert classify("Recruiter") == ("Human Resources", "Recruiter")
    assert classify("Chef") == ("Hospitality & Tourism", "Chef")
    assert classify("Quantity Surveyor") == ("Engineering & Construction", "Quantity Surveyor")
    assert classify("C++ Developer") == ("Technology & IT", "Software Engineer")
    assert classify("Machine Learning Engineer") == ("Technology & IT", "Machine Learning Engineer")
    assert classify("Sales Representative") == ("Sales & Business Development", "Sales Representative")


def test_industry_fallback():
    assert classify("Manager at Regional Bank")[0] == "Finance & Banking"
    assert classify("Administrator at University")[0] == "Education"
    assert classify("Clinic Administrator")[0] == "Healthcare"


def test_role_match_beats_industry_fallback():
    # "researcher" is a specific Science & Research role, so the explicit role
    # match wins over the looser "university" industry fallback.
    assert classify("Lab Researcher at University") == (
        "Science & Research", "Research Scientist")


def test_unknown_returns_other():
    assert classify("Quantum Widget Polisher") == ("Other", "Other")


def test_never_raises_on_garbage():
    assert classify("") == ("Other", "Other")
    assert classify(None) == ("Other", "Other")
    assert classify("   ") == ("Other", "Other")
    assert classify("!@#$%^&*()") == ("Other", "Other")


def test_deterministic():
    assert classify("Senior Software Engineer") == classify("Senior Software Engineer")


def test_description_never_changes_title_result():
    assert classify("Widget Polisher", "nurse and doctor work here") == ("Other", "Other")


def test_every_role_has_an_industry_and_vice_versa():
    for industry, roles in INDUSTRIES.items():
        assert roles, f"{industry} must offer at least one role"
        assert roles_for_industry(industry) == roles


def test_role_names_unique_across_industries():
    seen = {}
    for industry, roles in INDUSTRIES.items():
        for role in roles:
            assert role not in seen, f"role {role!r} appears in two industries"
            seen[role] = industry


def test_industries_list_matches_dict():
    assert INDUSTRIES_LIST == list(INDUSTRIES)


def test_roles_for_industry_unknown_is_empty():
    assert roles_for_industry("Not An Industry") == []


def test_taxonomy_is_large_enough_for_real_world():
    # The pickers should cover a meaningful slice of the working world.
    assert len(INDUSTRIES) >= 15
    assert sum(len(r) for r in INDUSTRIES.values()) >= 80
    assert "Technology & IT" in INDUSTRIES
    assert "Healthcare" in INDUSTRIES
    assert "Finance & Banking" in INDUSTRIES