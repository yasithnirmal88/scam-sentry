# Scam Sentry — Architecture Upgrade Spec

> Version 1.0 (Risk Assessment + Explainability Upgrade)

---

## 1. Goal

Upgrade Scam Sentry from a binary/hybrid "Fake vs Real" classifier into a structured, explainable **Job Risk Assessment** system, while preserving its current strengths (OCR, hybrid rules + ML, clean UI).

**New positioning:** Scam Sentry is an intelligent job-advertisement risk assessment tool.

- It detects scam indicators, ghost/stale signals, and suspicious patterns, then returns a clear risk level with evidence and recommended actions.
- **Never claim absolute authenticity.** Always speak in risk levels and evidence.

---

## 2. New Core Concepts

### 2.1 Risk Levels (Overall Verdict)

| Level | Emoji | Meaning |
|-------|-------|---------|
| Low | 🟢 | No major fraud or ghost indicators detected |
| Medium | 🟡 | Some suspicious characteristics present |
| High | 🔴 | Multiple strong warning signs |
| Critical | 🚨 | Strong indicators of scam (especially payment or sensitive data requests) |

### 2.2 Risk Categories (Multi-label)

- Scam Indicators
- Ghost/Stale
- Suspicious
- Likely Genuine

A posting can have multiple categories.

### 2.3 Confidence

- **High** — Multiple independent direct indicators agree
- **Medium** — Some indicators present, evidence partial
- **Low** — Few or ambiguous signals

---

## 3. Risk Indicator System (Normative)

All indicators are checked against the extracted text (and metadata when available).

**Severity determines the Overall Risk Level.**

### Critical Severity (any one → 🚨 Critical)

| ID | Indicator |
|----|-----------|
| C1 | Advance fee / registration fee / equipment payment requested |
| C2 | Request for highly sensitive personal data (bank details, NIC/SSN/passport, etc.) before a formal offer |
| C3 | Guaranteed unrealistic income + pressure tactics |
| C4 | Confirmed scam patterns (phishing language, fake check schemes, clear impersonation) |

### High Severity

| ID | Indicator |
|----|-----------|
| H1 | Recruiter uses free email domain (gmail, yahoo, outlook, etc.) while claiming to represent an established company |
| H2 | Strong urgency language ("apply within 24 hours", "positions filling fast") |
| H3 | Missing or extremely vague company information |
| H4 | Clear domain mismatch (email domain does not match claimed company) |
| H5 | Strong ghost/stale signals (evergreen language, repeatedly reposted, no concrete team/project details) |

### Medium Severity

| ID | Indicator |
|----|-----------|
| M1 | Vague role description (no responsibilities, team context, or deliverables) |
| M2 | No salary range when the market normally expects one |
| M3 | Unprofessional language / poor grammar (context-dependent) |
| M4 | Limited company online presence signals |

### Low Severity

| ID | Indicator |
|----|-----------|
| L1 | Minor title / responsibilities mismatch |
| L2 | Benefits not mentioned (often neutral) |
| L3 | Single repost (only meaningful with other signals) |

---

## 4. Determination Rules (First Match Wins)

1. Any Critical indicator → 🚨 Critical
2. ≥ 2 High indicators → 🔴 High
3. 1 High + ≥ 2 Medium → 🔴 High
4. 1 High alone → 🟡 Medium
5. ≥ 2 Medium → 🟡 Medium
6. Strong Ghost/Stale (H5) alone → 🟡 Medium
7. Only Low or none → 🟢 Low

---

## 5. New Response Structure (API + UI)

Every analysis must return this structure:

```json
{
  "overall_risk_level": "Critical | High | Medium | Low",
  "risk_categories": ["Scam Indicators", "Ghost/Stale", "..."],
  "confidence": "High | Medium | Low",
  "summary": "1-2 sentence careful summary",
  "key_indicators": [
    {
      "id": "C1",
      "name": "Advance fee requested",
      "severity": "Critical",
      "evidence": "short snippet from the text",
      "explanation": "Why this matters"
    }
  ],
  "employer_verification": {
    "company_website": "Found | Not found | Could not check",
    "email_domain_match": "Yes | No | N/A",
    "role_on_careers_page": "Yes | No | Unknown",
    "notes": "..."
  },
  "recommended_actions": [
    "Do not send any payment or registration fee",
    "Do not share bank details or national ID",
    "Verify the company website and email domain",
    "..."
  ],
  "hybrid_score": 0.87,
  "rule_score": 0.92,
  "ml_score": 0.81,
  "raw_text_preview": "..."
}
```

### Language Rules (Mandatory)

- **Never say "This is a scam" or "This is fake".**
- Always use: "High risk of…", "Multiple strong indicators suggest…", "This posting shows patterns consistent with…".
- Always allow legitimate explanations when possible.

---

## 6. Hybrid Scoring Update

Keep the existing hybrid approach but make it **secondary** to the indicator system:

- **Final Risk Level** = Determined by Indicator Rules (primary)
- **Hybrid Score** = 0.55 × Rule Score + 0.45 × ML Score (supporting signal)

**Score Floor Rule (already good — keep and strengthen):**
- If any Critical indicator (C1–C4) is present → Overall Risk Level **must** be Critical, regardless of ML score.

---

## 7. Architecture Changes

### Current Flow

```
Input → OCR → Preprocessing → TF-IDF + Rule Features → GradientBoosting → Hybrid Score → Verdict
```

### New Recommended Flow

```
Input → OCR → Preprocessing
                ↓
        ┌───────┴────────┐
        ↓                ↓
   Rule Engine      ML Classifier
   (Indicators)     (TF-IDF + features)
        ↓                ↓
        └───────┬────────┘
                ↓
        Risk Engine
   (Determination Rules + Score Floor)
                ↓
     Structured Response
   (Risk Level + Categories + Evidence + Actions)
```

### New Modules (suggested)

```
scam_sentry/
├── app.py
├── config.py                 # All thresholds, weights, paths
├── ocr/
├── nlp/
├── features/
│   ├── rule_indicators.py    # C1–C4, H1–H5, M1–M4, L1–L3
│   └── ml_features.py
├── risk/
│   ├── engine.py             # Determination rules
│   ├── verification.py       # Employer checks (lightweight)
│   └── actions.py            # Recommended Actions generator
├── models/
├── api/
└── tests/
```

---

## 8. Employer Verification (Lightweight)

Perform only with already available information or very cheap checks:

- Does the text contain a company website?
- Does the contact email domain match the claimed company name/domain?
- Is company information missing or extremely vague?

Mark as "Could not check" when data is insufficient. **Never invent results.**

---

## 9. Recommended Actions Generator

Dynamically generate 3–5 prioritized actions based on fired indicators:

- **Critical/High** → Lead with safety actions (no payment, no sensitive data)
- **Domain mismatch / free email** → Verification steps
- **Ghost signals** → "Confirm the role is still active"
- **Low risk** → Lighter confirmation advice

---

## 10. Backward Compatibility & Migration

- Keep existing `/api/analyze/text` and `/api/analyze/file` endpoints working.
- Prefer adding a new richer response format (versioned if needed).
- UI should be updated to display:
  - Big Risk Level badge
  - Categories
  - Key Indicators with evidence
  - Recommended Actions
  - Supporting hybrid score (secondary)

---

## 11. Success Criteria

The upgraded Scam Sentry should be able to:

- Correctly flag clear advance-fee scams as 🚨 Critical with C1/C2 evidence.
- Flag free-email + urgency + vague company as High or Medium risk.
- Give Low risk to clean, professional postings from known companies.
- Always return explainable evidence and actionable next steps.
- **Never use absolute "fake/scam" language.**

---

*End of spec. Scam Sentry v1.0 — Risk Assessment + Explainability Upgrade.*
