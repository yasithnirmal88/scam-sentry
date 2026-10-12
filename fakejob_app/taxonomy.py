"""
taxonomy.py
-----------
Deterministic world industry / job-role classification for scanned listings.

The public job boards behind the scanner expose little structure (title +
free text), so industry and role are inferred from the posting title using
explicit keyword rules. This is a display / filter aid for the dashboard
("browse by industry, then by role") -- it is NOT part of the Risk Engine and
never influences a risk verdict.

Design rules:

- ``_FACETS`` is the single source of truth: ordered ``(industry, role,
  keywords)`` tuples. ``INDUSTRIES`` (the dashboard picker data) is derived
  from it, so every listed role always has keywords and an industry.
- Order matters: the first role whose keyword matches wins, so specific /
  cross-industry variants (e.g. "Construction Project Manager") are placed
  before generic ones (e.g. "Project Manager").
- "Other" is always a valid result. Unknown listings must never crash a scan
  or fake a label.
"""

from __future__ import annotations

import re
from typing import Any

_OTHER = "Other"

_FACETS: list[tuple[str, str, tuple[str, ...]]] = [
    # --- Engineering & Construction first: "Construction Project Manager"
    # must beat the generic "Project Manager" below. -------------------------
    ("Engineering & Construction", "Civil Engineer",
     ("civil engineer",)),
    ("Engineering & Construction", "Mechanical Engineer",
     ("mechanical engineer",)),
    ("Engineering & Construction", "Electrical Engineer",
     ("electrical engineer", "electronics engineer",)),
    ("Engineering & Construction", "Structural Engineer",
     ("structural engineer",)),
    ("Engineering & Construction", "Construction Project Manager",
     ("construction project manager", "construction manager",
      "general contractor", "site manager", "site supervisor")),
    ("Engineering & Construction", "Architect",
     ("architect", "architecture")),
    ("Engineering & Construction", "Quantity Surveyor",
     ("quantity surveyor", "cost estimator", "surveyor")),
    ("Engineering & Construction", "Draftsperson",
     ("drafter", "draftsperson", "cad technician", "bim technician")),
    ("Engineering & Construction", "Construction Worker",
     ("construction worker", "construction laborer", "site worker")),

    # --- Technology & IT ----------------------------------------------------
    ("Technology & IT", "Software Engineer",
     ("software engineer", "software developer", "backend engineer",
      "backend developer", "frontend engineer", "frontend developer",
      "full stack", "full-stack", "web developer", "web engineer",
      "application developer", "developer", "programmer",
      "wordpress developer", "c++", "python developer", "java developer",
      "golang developer", "ruby developer", "node developer")),
    ("Technology & IT", "Machine Learning Engineer",
     ("machine learning", "ml engineer", "ai engineer", "deep learning",
      "llm engineer", "prompt engineer", "ai scientist", "mlops")),
    ("Technology & IT", "Data Engineer",
     ("data engineer", "data infrastructure", "data pipelines", "etl")),
    ("Technology & IT", "Data Scientist",
     ("data scientist", "data science", "statistician")),
    ("Technology & IT", "Data Analyst",
     ("data analyst", "business intelligence analyst", "bi analyst",
      "analytics engineer", "sql analyst")),
    ("Technology & IT", "DevOps Engineer",
     ("devops", "platform engineer", "site reliability", "sre",
      "infrastructure engineer", "release engineer", "cloud engineer")),
    ("Technology & IT", "QA Engineer",
     ("qa engineer", "quality assurance engineer", "quality assurance analyst",
      "test engineer", "software tester", "automation engineer",
      "sdets", "sdet")),
    ("Technology & IT", "Cybersecurity Analyst",
     ("security engineer", "cybersecurity", "cyber security", "security analyst",
      "penetration tester", "soc analyst", "infosec", "information security")),
    ("Technology & IT", "Systems Administrator",
     ("systems administrator", "system administrator", "sysadmin",
      "network administrator", "network engineer", "it administrator",
      "database administrator", "dba")),
    ("Technology & IT", "IT Support",
     ("it support", "tech support", "desktop support", "it technician",
      "system support")),
    ("Technology & IT", "UI/UX Designer",
     ("ux designer", "ui designer", "ui/ux", "user experience",
      "user interface", "ux engineer")),
    ("Technology & IT", "Product Manager",
     ("project manager", "program manager", "delivery manager",
      "agile coach", "scrum master", "product manager")),
    ("Technology & IT", "Mobile Developer",
     ("ios developer", "android developer", "mobile developer",
      "flutter developer", "react native")),
    ("Technology & IT", "Game Developer",
     ("game developer", "game programmer", "unity developer", "unreal")),

    # --- Healthcare ---------------------------------------------------------
    ("Healthcare", "Physician",
     ("physician", "medical doctor", "doctor", "surgeon","pediatrician",
      "general practitioner", "specialist doctor")),
    ("Healthcare", "Registered Nurse",
     ("registered nurse", "staff nurse", "icu nurse", "charge nurse",
      "nurse practitioner", "licensed practical nurse", "care nurse", "nurse")),
    ("Healthcare", "Pharmacist",
     ("pharmacist", "pharmacy technician", "pharmaceutical")),
    ("Healthcare", "Dentist",
     ("dentist", "dental surgeon", "dental hygienist", "orthodontist")),
    ("Healthcare", "Therapist",
     ("therapist", "counselor", "counsellor", "physiotherapist",
      "physical therapist", "occupational therapist", "speech therapist",
      "clinical psychologist", "psychologist")),
    ("Healthcare", "Medical Technologist",
     ("medical technologist", "medical laboratory", "pathology technician",
      "radiology technician", "lab technician", "imaging technician",
      "sonographer")),
    ("Healthcare", "Caregiver",
     ("caregiver", "care giver", "home health aide", "nursing assistant",
      "personal care")),
    ("Healthcare", "Medical Assistant",
     ("medical assistant", "clinical assistant", "hospital assistant",
      "patient care technician")),
    ("Healthcare", "Healthcare Administrator",
     ("healthcare administrator", "hospital administrator", "health admin",
      "practice manager", "clinical manager")),

    # --- Finance & Banking --------------------------------------------------
    ("Finance & Banking", "Financial Analyst",
     ("financial analyst", "finance analyst", "equity research",
      "fp&a", "fp&a analyst")),
    ("Finance & Banking", "Quantitative Analyst",
     ("quantitative analyst", "quant analyst", "quantitative developer")),
    ("Finance & Banking", "Accountant",
     ("accountant", "accounting", "bookkeeper", "accounts payable",
      "accounts receivable", "tax accountant", "staff accountant")),
    ("Finance & Banking", "Auditor",
     ("auditor", "internal audit", "external audit", "tax auditor",
      "forensic accountant")),
    ("Finance & Banking", "Investment Banker",
     ("investment banker", "investment banking", "private equity",
      "hedge fund", "corporate development")),
    ("Finance & Banking", "Risk Analyst",
     ("risk analyst", "credit analyst", "market risk analyst",
      "credit risk", "underwriter", "underwriting")),
    ("Finance & Banking", "Financial Advisor",
     ("financial advisor", "financial planner", "wealth manager",
      "financial consultant", "insurance agent", "insurance broker")),
    ("Finance & Banking", "Bank Teller",
     ("bank teller", "teller", "customer service banker")),
    ("Finance & Banking", "Loan Officer",
     ("loan officer", "mortgage officer", "mortgage broker",
      "credit officer")),

    # --- Education ----------------------------------------------------------
    ("Education", "Teacher",
     ("teacher", "teaching", "kindergarten", "high school", "middle school",
      "elementary school", "esl teacher", "substitute teacher", "instructor")),
    ("Education", "Professor",
     ("professor", "faculty", "lecturer", "postdoctoral fellow",
      "academic")),
    ("Education", "Tutor",
     ("tutor", "private tutor")),
    ("Education", "Curriculum Developer",
     ("curriculum developer", "curriculum designer", "instructional designer",
      "training developer", "instructional coordinator")),
    ("Education", "School Administrator",
     ("school principal", "principal", "school administrator",
      "education administrator", "education coordinator", "dean")),
    ("Education", "Education Consultant",
     ("education consultant", "educational consultant", "academic advisor",
      "career counselor", "career counsellor")),

    # --- Marketing & Media --------------------------------------------------
    ("Marketing & Media", "Marketing Manager",
     ("marketing manager", "marketing lead", "head of marketing",
      "brand manager", "campaign manager", "growth marketing",
      "marketing coordinator", "marketing director", "digital marketing")),
    ("Marketing & Media", "Content Writer",
     ("content writer", "copywriter", "technical writer", "blog writer",
      "content strategist", "content editor", "editor", "author")),
    ("Marketing & Media", "Social Media Manager",
     ("social media", "community manager", "social media manager",
      "influencer")),
    ("Marketing & Media", "SEO Specialist",
     ("seo specialist", "seo", "search engine optimization",
      "search engine marketing", "sem specialist")),
    ("Marketing & Media", "Graphic Designer",
     ("graphic designer", "visual designer", "brand designer",
      "graphic artist")),
    ("Marketing & Media", "Video Editor",
     ("video editor", "video producer", "videographer",
      "motion graphics")),
    ("Marketing & Media", "PR Specialist",
     ("public relations", "pr specialist", "communications specialist",
      "press officer", "media relations")),
    ("Marketing & Media", "Media Buyer",
     ("media buyer", "ppc specialist", "google ads", "performance marketing",
      "paid media", "digital marketer")),

    # --- Sales & Business Development --------------------------------------
    ("Sales & Business Development", "Sales Representative",
     ("sales representative", "sales rep", "sales executive",
      "account executive", "sales associate", "salesperson",
      "inside sales", "outside sales", "b2b sales", "field sales",
      "sales consultant", "sales agent")),
    ("Sales & Business Development", "Account Manager",
     ("account manager", "key account manager", "client manager")),
    ("Sales & Business Development", "Business Development Manager",
     ("business development", "bdm", "partnership manager",
      "growth manager", "alliances manager", "development executive")),
    ("Sales & Business Development", "Sales Manager",
     ("sales manager", "regional sales", "head of sales",
      "national accounts", "sales director")),
    ("Sales & Business Development", "Customer Success Manager",
     ("customer success", "success manager", "renewals manager")),

    # --- Customer Service ---------------------------------------------------
    ("Customer Service", "Customer Support Agent",
     ("customer support", "customer service", "support agent",
      "support specialist", "helpdesk", "help desk", "service desk",
      "call center", "contact center", "technical support")),
    ("Customer Service", "Client Services Specialist",
     ("client services", "member services", "patient services")),
    ("Customer Service", "Support Team Lead",
     ("support lead", "support manager", "support team lead",
      "service delivery manager")),
    ("Customer Service", "Receptionist",
     ("receptionist", "front office")),

    # --- Human Resources ----------------------------------------------------
    ("Human Resources", "Recruiter",
     ("recruiter", "talent acquisition", "staffing", "talent sourcer",
      "headhunter")),
    ("Human Resources", "HR Generalist",
     ("hr generalist", "human resources generalist", "hr coordinator",
      "hr administrator", "people operations")),
    ("Human Resources", "HR Manager",
     ("hr manager", "human resources manager", "head of hr",
      "hr director", "people partner")),
    ("Human Resources", "Payroll Specialist",
     ("payroll specialist", "payroll", "compensation analyst",
      "benefits specialist", "benefits administrator")),

    # --- Legal & Compliance -------------------------------------------------
    ("Legal & Compliance", "Lawyer",
     ("lawyer", "attorney", "solicitor", "legal counsel", "in-house counsel",
      "litigator")),
    ("Legal & Compliance", "Paralegal",
     ("paralegal", "legal assistant", "legal secretary", "legal analyst",
      "legal researcher")),
    ("Legal & Compliance", "Compliance Officer",
     ("compliance officer", "compliance analyst", "regulatory compliance",
      "aml analyst", "anti-money laundering", "kyc analyst",
      "risk and compliance")),
    ("Legal & Compliance", "Data Protection Officer",
     ("data protection officer", "privacy officer", "dpo", "gdpr")),

    # --- Science & Research -------------------------------------------------
    ("Science & Research", "Research Scientist",
     ("research scientist", "research fellow", "scientist", "postdoctoral",
      "postdoc", "r&d scientist", "researcher")),
    ("Science & Research", "Laboratory Technician",
     ("laboratory technician", "lab technician", "lab assistant",
      "laboratory assistant", "sample testing")),
    ("Science & Research", "Research Assistant",
     ("research assistant", "research associate", "clinical research")),
    ("Science & Research", "Biotechnologist",
     ("biotechnologist", "biologist", "biochemist", "molecular biology",
      "genomics", "microbiologist")),

    # --- Hospitality & Tourism ---------------------------------------------
    ("Hospitality & Tourism", "Hotel Manager",
     ("hotel manager", "resort manager", "lodging manager",
      "duty manager")),
    ("Hospitality & Tourism", "Chef",
     ("chef", "sous chef", "head chef", "cook", "culinary",
      "kitchen manager")),
    ("Hospitality & Tourism", "Front Desk Agent",
     ("front desk", "guest service", "concierge", "front office agent")),
    ("Hospitality & Tourism", "Travel Agent",
     ("travel agent", "travel consultant", "tourism manager",
      "tour guide")),
    ("Hospitality & Tourism", "Event Coordinator",
     ("event coordinator", "event manager", "event planner",
      "wedding planner", "event organizer")),
    ("Hospitality & Tourism", "Waiter/Waitress",
     ("waiter", "waitress", "bartender", "barista", "server")),
    ("Hospitality & Tourism", "Housekeeper",
     ("housekeeper", "housekeeping", "maid", "cleaner", "janitor",
      "cleaning staff")),

    # --- Agriculture & Environment -----------------------------------------
    ("Agriculture & Environment", "Farm Manager",
     ("farm manager", "farmhand", "farmer", "horticulturist",
      "ranch manager", "agricultural manager")),
    ("Agriculture & Environment", "Agronomist",
     ("agronomist", "agricultural scientist", "crop scientist",
      "soil scientist")),
    ("Agriculture & Environment", "Environmental Scientist",
     ("environmental scientist", "environmental engineer",
      "ecologist", "sustainability", "hse officer", "ehs officer",
      "environmental health")),
    ("Agriculture & Environment", "Agricultural Technician",
     ("agricultural technician", "vineyard", "greenhouse")),

    # --- Manufacturing & Logistics -----------------------------------------
    ("Manufacturing & Logistics", "Production Operator",
     ("production operator", "machine operator", "production technician",
      "assembly line", "manufacturing technician")),
    ("Manufacturing & Logistics", "Supply Chain Analyst",
     ("supply chain", "logistics analyst", "inventory analyst",
      "demand planner", "supply planner", "supply chain manager")),
    ("Manufacturing & Logistics", "Warehouse Associate",
     ("warehouse", "picker packer", "packer", "forklift operator",
      "stock clerk")),
    ("Manufacturing & Logistics", "Logistics Coordinator",
     ("logistics coordinator", "logistics manager", "dispatcher",
      "shipping", "freight", "fulfillment")),
    ("Manufacturing & Logistics", "Procurement Specialist",
     ("procurement", "purchasing", "sourcing specialist", "buyer",
      "vendor manager", "supplier manager")),
    ("Manufacturing & Logistics", "Quality Control Inspector",
     ("quality control", "quality assurance inspector", "qc inspector",
      "qaqc", "quality inspector")),

    # --- Government & Public Sector ----------------------------------------
    ("Government & Public Sector", "Policy Analyst",
     ("policy analyst", "public policy", "policy advisor",
      "legislative analyst", "policy officer")),
    ("Government & Public Sector", "Public Administrator",
     ("public administrator", "public sector", "civil service",
      "government", "municipal", "regulatory officer")),
    ("Government & Public Sector", "Urban Planner",
     ("urban planner", "city planner", "regional planner", "zoning")),

    # --- Real Estate --------------------------------------------------------
    ("Real Estate", "Real Estate Agent",
     ("real estate agent", "realtor", "real estate associate",
      "real estate consultant")),
    ("Real Estate", "Property Manager",
     ("property manager", "property management", "estate manager")),
    ("Real Estate", "Appraiser",
     ("appraiser", "property appraiser", "real estate valuer", "assessor")),
    ("Real Estate", "Leasing Agent",
     ("leasing agent", "leasing consultant", "leasing manager")),

    # --- Creative & Design --------------------------------------------------
    ("Creative & Design", "Product Designer",
     ("product designer", "design system", "product design")),
    ("Creative & Design", "UX Researcher",
     ("ux researcher", "user researcher", "usability")),
    ("Creative & Design", "Art Director",
     ("art director", "creative director", "creative lead")),
    ("Creative & Design", "Illustrator",
     ("illustrator", "illustration")),
    ("Creative & Design", "Motion Designer",
     ("motion designer", "2d artist", "3d artist", "animator")),
    ("Creative & Design", "Photographer",
     ("photographer", "photo editor", "photography")),
    ("Creative & Design", "Copy Editor",
     ("copy editor", "proofreader", "sub editor")),
]

INDUSTRIES: dict[str, list[str]] = {}
for _industry, _role, _kws in _FACETS:
    INDUSTRIES.setdefault(_industry, []).append(_role)

INDUSTRIES_LIST: list[str] = list(INDUSTRIES)

# A few well-known industry labels that don't map to a specific role come
# through an explicit industry fallback after the role table misses.
_INDUSTRY_FALLBACK: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Finance & Banking", ("banking", "finance", "bank")),
    ("Healthcare", ("clinic", "hospital", "medical")),
    ("Education", ("university", "school")),
    ("Marketing & Media", ("media", "advertising", "news")),
    ("Hospitality & Tourism", ("hotel", "restaurant", "tourism")),
    ("Engineering & Construction", ("construction", "engineering")),
)

_WORD_RE = re.compile(r"[^a-z0-9+#]+")


def _norm(text: Any) -> str:
    return _WORD_RE.sub(" ", str(text or "").lower()).strip()


def _has(text: str, keyword_phrase: str) -> bool:
    """True when keyword_phrase appears as a whole phrase in normalized text."""
    return (" " + keyword_phrase + " ") in (" " + text + " ")


def roles_for_industry(industry: str) -> list[str]:
    """Roles offered by one industry ([] for unknown labels)."""
    return list(INDUSTRIES.get(industry, []))


def classify(title: Any, description: Any = "") -> tuple[str, str]:
    """Map a posting title to (industry, role). Deterministic; never raises.

    Uses the title only -- free-text descriptions are too noisy to infer a
    role from. Returns ("Other", "Other") when nothing matches.
    """
    text = _norm(title)
    if not text:
        return _OTHER, _OTHER
    for industry, role, keywords in _FACETS:  # ordered: first match wins
        for keyword in keywords:
            if _has(text, _norm(keyword)):
                return industry, role
    for industry, keywords in _INDUSTRY_FALLBACK:
        for keyword in keywords:
            if _has(text, _norm(keyword)):
                return industry, _OTHER
    return _OTHER, _OTHER