"""
risk/actions.py
---------------
Recommended Actions generator: 3-5 prioritized, actionable bullets based on
fired indicators and final risk level. Helpful tone, non-alarmist when low.
"""

SAFETY_NO_PAYMENT = "Do not send any payment, registration fee, or deposit"
SAFETY_NO_DATA = "Do not share bank details, national ID, passport, or card data"
VERIFY_DOMAIN = "Verify the company website and that the contact email uses the official company domain"
VERIFY_COMPANY = "Verify the employer through its official website or careers page before engaging"
VERIFY_ACTIVE = "Confirm the role is still active on the employer's official careers page"
CAUTION_PERSONAL = "Avoid sharing sensitive personal details until the employer is verified"
LIGHT_CHECK = "Do a light check: official website, careers page listing, and contact details"


def generate_actions(fired, level):
    """Return 3-5 prioritized recommended actions."""
    ids = {d.get("id") for d in (fired or [])}
    actions = []

    if level == "Critical":
        actions.append(SAFETY_NO_PAYMENT)
        actions.append(SAFETY_NO_DATA)
        if ids & {"H1", "H4"}:
            actions.append(VERIFY_DOMAIN)
        else:
            actions.append(VERIFY_COMPANY)
        actions.append("Stop engaging and report the posting if pressure or payment demands continue")
        return actions[:5]

    if level == "High":
        if ids & {"C1", "H2", "C3"}:
            actions.append(SAFETY_NO_PAYMENT)
        if ids & {"C2", "C4"}:
            actions.append(SAFETY_NO_DATA)
        if ids & {"H1", "H4"}:
            actions.append(VERIFY_DOMAIN)
        if "H3" in ids or "M4" in ids:
            actions.append(VERIFY_COMPANY)
        if "H5" in ids:
            actions.append(VERIFY_ACTIVE)
        actions.append(CAUTION_PERSONAL)
        # Deduplicate, keep order, cap at 5, floor at 3.
        seen = []
        for a in actions:
            if a not in seen:
                seen.append(a)
        while len(seen) < 3:
            for fallback in (VERIFY_COMPANY, VERIFY_ACTIVE, LIGHT_CHECK):
                if fallback not in seen:
                    seen.append(fallback)
                    break
        return seen[:5]

    if level == "Medium":
        if ids & {"H1", "H4"}:
            actions.append(VERIFY_DOMAIN)
        if "H5" in ids or "L3" in ids:
            actions.append(VERIFY_ACTIVE)
        actions.append(VERIFY_COMPANY)
        actions.append(CAUTION_PERSONAL)
        if "M2" in ids:
            actions.append("Ask for a written offer with clear compensation before proceeding")
        seen = []
        for a in actions:
            if a not in seen:
                seen.append(a)
        return seen[:5]

    # Low
    actions = [
        LIGHT_CHECK,
        "Confirm the role and team details in an interview before sharing sensitive data",
        "Proceed normally but stay alert for later fee or data requests",
    ]
    return actions[:3]
