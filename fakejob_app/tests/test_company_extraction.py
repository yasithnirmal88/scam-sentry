"""Part B (Option 1): labeled company values must not swallow the next field."""

from fraud_features import extract_company_name


def test_header_value_cut_before_next_field():
    assert extract_company_name("Company: Initech LLC. Location: Remote") == "Initech LLC."
    assert extract_company_name("Company: Acme Corp. Salary: $50k") == "Acme Corp."
    assert extract_company_name("Employer: Globex Inc. Email: hr@globex.com") == "Globex Inc."


def test_plain_header_values_unchanged():
    assert extract_company_name("Company: Acme") == "Acme"
    assert extract_company_name("Company: Location Labs") == "Location Labs"
    assert extract_company_name("Company: Wayve") == "Wayve"


def test_extraction_still_graceful():
    assert extract_company_name("") is None
    assert extract_company_name(None) is None
    assert extract_company_name("No company here at all, just a role.") is None
