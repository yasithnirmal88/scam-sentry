"""
risk/verification.py
--------------------
Lightweight employer verification using only already-available information.

Never invents results: marks "Could not check" / "Unknown" when data is
insufficient.
"""

import re

from fraud_features import URL_PATTERN, EMAIL_PATTERN, extract_company_name


def verify_employer(text, fired=None):
    """Return employer_verification dict per spec structure."""
    text = text or ""
    fired_ids = {d.get("id") for d in (fired or [])}

    urls = URL_PATTERN.findall(text)
    emails = EMAIL_PATTERN.findall(text)
    company = extract_company_name(text)

    # Company website present?
    if urls:
        company_website = "Found"
    elif company is None:
        company_website = "Could not check"
    else:
        company_website = "Not found"

    # Email domain match?
    if not emails:
        email_domain_match = "N/A"
    elif company is None:
        email_domain_match = "N/A"
    else:
        if "H4" in fired_ids:
            email_domain_match = "No"
        elif "H1" in fired_ids:
            email_domain_match = "No"
        else:
            # Compare first non-free email domain to company name loosely.
            from fraud_features import FREE_EMAIL_DOMAINS
            free = set(FREE_EMAIL_DOMAINS)
            checked = False
            match = None
            simplified = re.sub(r"[^a-z0-9]", "", company.lower())
            for e in emails:
                domain = e.split("@")[-1].lower().strip(".,;)]")
                if domain in free:
                    continue
                checked = True
                host = re.sub(r"[^a-z0-9]", "", domain)
                if simplified[:5] in host or host[:5] in simplified:
                    match = True
                    break
                match = False
            if not checked:
                email_domain_match = "N/A"
            else:
                email_domain_match = "Yes" if match else "No"

    notes_parts = []
    if company:
        notes_parts.append("Employer name detected: %s." % company)
    else:
        notes_parts.append("No clear employer name found; verification is limited.")
    if urls:
        notes_parts.append("%d website link(s) present in text." % len(urls))
    else:
        notes_parts.append("No website link present in text.")
    if emails:
        notes_parts.append("%d contact email(s) present." % len(emails))
    else:
        notes_parts.append("No contact email present.")
    if "H5" in fired_ids or "L3" in fired_ids:
        notes_parts.append("Repost/evergreen wording present; confirm the role is still active.")

    return {
        "company_website": company_website,
        "email_domain_match": email_domain_match,
        "role_on_careers_page": "Unknown",
        "notes": " ".join(notes_parts),
    }
