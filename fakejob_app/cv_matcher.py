"""
cv_matcher.py
-------------
CV -> scanned-job relevance matching.

This sits BESIDE the Risk Engine and does a different job:

- Risk Engine (``risk/``) = is this posting safe? (authoritative, stored per job)
- CV Matcher (here)      = is this posting relevant to *this candidate*?

The matcher only ranks jobs that are already stored, and it never changes a
risk level -- it copies the engine's ``overall_risk_level`` through untouched.

Scoring is deliberately transparent and dependency-light:

- a curated skill/tool vocabulary gives explicit, human-readable
  ``matched_terms`` (keyword overlap), and
- TF-IDF + cosine similarity (scikit-learn, already a dependency) catches
  wording similarity beyond the vocabulary.

The two are blended (``config.CV_TFIDF_WEIGHT`` / ``config.CV_TERM_WEIGHT``).
Ranking puts higher fit first but strongly prefers safer listings: Critical
postings are pushed to the very bottom and are never a top recommendation.

No ML model is trained here and no CV text is ever sent to an LLM -- matching
is deterministic and local.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

import config
from text_processing import STOPWORDS, preprocess
import taxonomy

try:  # scikit-learn is a runtime dependency; degrade to term overlap if absent.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _SKLEARN = True
except Exception:  # pragma: no cover - defensive
    _SKLEARN = False


# ---------------------------------------------------------------------------
# Curated vocabulary. Phrases are lowercase and matched as whole words against
# the normalized CV text. Not exhaustive by design -- a practical signal set.
# ---------------------------------------------------------------------------
KNOWN_SKILLS = {
    "communication", "leadership", "teamwork", "problem solving",
    "critical thinking", "time management", "project management",
    "customer service", "negotiation", "presentation", "public speaking",
    "data analysis", "data entry", "research", "reporting", "documentation",
    "budgeting", "forecasting", "accounting", "bookkeeping", "auditing",
    "financial analysis", "recruiting", "onboarding", "training",
    "sales", "marketing", "seo", "content writing", "copywriting",
    "social media", "branding", "graphic design", "ux design", "ui design",
    "product management", "agile", "scrum", "kanban",
    "testing", "quality assurance", "debugging", "troubleshooting",
    "machine learning", "deep learning", "data science", "data engineering",
    "statistics", "patient care", "nursing", "clinical",
    "teaching", "curriculum", "lesson planning", "logistics", "procurement",
    "supply chain", "inventory management", "warehouse", "manufacturing",
    "quality control", "compliance", "risk management", "legal research",
    "contracts", "customer support", "help desk", "payroll",
    "etl", "data visualization", "cybersecurity", "network administration",
}

KNOWN_TOOLS = {
    # languages
    "python", "javascript", "typescript", "java", "c++", "c#",
    "go", "golang", "ruby", "php", "rust", "kotlin", "swift", "scala",
    "matlab", "bash", "powershell", "sql", "nosql", "html", "css",
    "sass", "scss",
    # frontend / backend
    "react", "react native", "angular", "vue", "svelte", "next.js", "node.js",
    "express", "django", "flask", "fastapi", "spring boot", "laravel",
    "ruby on rails", ".net", "asp.net", "jquery", "bootstrap", "tailwind",
    "redux", "graphql", "rest api", "grpc",
    # data / ml
    "numpy", "pandas", "scipy", "scikit-learn", "tensorflow", "pytorch",
    "keras", "opencv", "spark", "pyspark", "hadoop", "kafka", "airflow",
    "dbt", "snowflake", "bigquery", "redshift", "databricks", "tableau",
    "power bi", "looker", "excel", "jupyter", "matplotlib", "seaborn",
    "plotly", "nlp", "llm", "transformers", "langchain",
    # databases
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis",
    "elasticsearch", "cassandra", "dynamodb", "oracle", "mariadb", "neo4j",
    # cloud / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
    "ansible", "jenkins", "gitlab ci", "github actions", "circleci",
    "linux", "git", "github", "gitlab", "bitbucket", "nginx", "apache",
    "prometheus", "grafana", "serverless", "aws lambda", "aws lambda",
    # dev tooling / collaboration
    "jira", "confluence", "slack", "trello", "asana", "notion",
    "salesforce", "hubspot", "sap", "power bi", "tableau",
    # design
    "figma", "adobe xd", "photoshop", "illustrator", "canva",
}

# Section headings we can detect reliably enough to report.
_SECTION_KEYS = {
    "skills", "technical skills", "core skills", "experience",
    "work experience", "professional experience", "employment",
    "education", "projects", "certifications", "certificates", "summary",
    "professional summary", "profile", "objective", "languages",
    "awards", "publications", "interests",
}

_NORM_RE = re.compile(r"[^a-z0-9+#.]+")
# Tokens keep internal ``.`` (node.js) and trailing ``+#`` (c++, c#) but not a
# trailing sentence period.
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#]*(?:\.[a-z0-9+#]+)*")

# Risk ordering: higher = more dangerous. The penalty only affects the default
# SORT (fit first, safer preferred); it never rewrites a risk level.
_RISK_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
_RISK_PENALTY = {"Low": 0, "Medium": 6, "High": 20, "Critical": 1000}

_SKILLS_BY_LEN = sorted(KNOWN_SKILLS, key=len, reverse=True)
_TOOLS_BY_LEN = sorted(KNOWN_TOOLS, key=len, reverse=True)


def _norm(text: Any) -> str:
    """Lowercase, keep ``+ # .`` (so c++, c#, node.js survive), collapse rest."""
    return _NORM_RE.sub(" ", str(text or "").lower()).strip()


def _has_phrase(text: str, phrase: str) -> bool:
    return (" " + phrase + " ") in (" " + text + " ")


def _detect_phrases(text: str, vocab: list[str]) -> list[str]:
    nn = _norm(text)
    return [p for p in vocab if _has_phrase(nn, p)]


def _detect_sections(text: str) -> list[str]:
    """Detect section headings, including the inline ``Skills: ...`` form."""
    found: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().lower().rstrip(":")
        if not line:
            continue
        head = line.split(":", 1)[0].strip()
        for candidate in (line, head):
            if (candidate and len(candidate) <= 40
                    and candidate in _SECTION_KEYS and candidate not in found):
                found.append(candidate)
    return found


def _detect_role_titles(text: str) -> list[str]:
    """Roles inferred by reusing the taxonomy classifier on CV lines.

    Titles often appear in headings/experience bullets, so each short-ish line
    is classified and the distinct non-"Other" roles are kept.
    """
    roles: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or len(line) > 80:
            continue
        _industry, role = taxonomy.classify(line)
        if role != "Other" and role not in roles:
            roles.append(role)
    return roles[:10]


def extract_signals(text: str) -> dict[str, Any]:
    """Lightweight matching signals from CV text. Never raises.

    Returns a stable dict with ``skills``, ``tools``, ``role_titles``,
    ``keywords`` (frequent content tokens), ``sections`` plus size fields.
    """
    text = str(text or "")
    skills = _detect_phrases(text, _SKILLS_BY_LEN)
    tools = _detect_phrases(text, _TOOLS_BY_LEN)

    tokens = [t for t in _WORD_RE.findall(_norm(text))
              if len(t) > 2 and t not in STOPWORDS]
    keywords = [w for w, _n in Counter(tokens).most_common(25)]

    return {
        "skills": sorted(set(skills)),
        "tools": sorted(set(tools)),
        "role_titles": _detect_role_titles(text),
        "keywords": keywords,
        "sections": _detect_sections(text),
        "word_count": len(_WORD_RE.findall(_norm(text))),
        "char_count": len(text),
    }


def _signal_terms(signals: dict[str, Any]) -> list[str]:
    """Phrases used for explicit keyword overlap (skills, tools, role titles)."""
    terms = list(signals.get("skills") or []) + list(signals.get("tools") or [])
    terms += [_norm(r) for r in (signals.get("role_titles") or [])]
    # De-dupe, longest first so "machine learning" beats "learning".
    ordered: dict[str, None] = {}
    for term in sorted((t.strip() for t in terms), key=len, reverse=True):
        if term:
            ordered.setdefault(term, None)
    return list(ordered)


def _cosine_scores(cv_text: str, job_texts: list[str]) -> list[float]:
    """TF-IDF + cosine similarity of the CV against each job. Zeros on failure."""
    if not _SKLEARN or not job_texts:
        return [0.0] * len(job_texts)
    docs = [preprocess(cv_text)] + [preprocess(t) for t in job_texts]
    try:
        vectorizer = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
            max_features=20000,
        )
        matrix = vectorizer.fit_transform(docs)
        sims = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        return [float(max(0.0, min(1.0, s))) for s in sims]
    except Exception:
        return [0.0] * len(job_texts)


def _job_text(job: dict[str, Any]) -> str:
    parts = [
        job.get("title") or "",
        job.get("industry") or "",
        job.get("job_role") or "",
        (job.get("description") or "")[:2500],
    ]
    return " ".join(p for p in parts if p)


def _reason(matched: list[str], cosine: float) -> str:
    if matched:
        return "Matches your CV on: " + ", ".join(matched[:5]) + "."
    if cosine >= 0.15:
        return "Wording and topics are similar to your CV."
    return "Broadly related posting (low keyword overlap)."


def _risk_penalty(level: str) -> int:
    return _RISK_PENALTY.get((level or "").capitalize(), 0)


def match_jobs(cv_text: str, jobs: list[dict[str, Any]],
               signals: Optional[dict[str, Any]] = None,
               min_fit: int = 0, risk_level: Optional[str] = None,
               exclude_risky: bool = False,
               limit: int = 50) -> list[dict[str, Any]]:
    """Rank ``jobs`` by relevance to ``cv_text``.

    ``min_fit`` drops weak matches; ``risk_level`` keeps a single level; and
    ``exclude_risky`` removes High + Critical listings. Results are ordered by
    fit with a safety preference (Critical always last). Never raises.
    """
    jobs = list(jobs or [])
    if not jobs:
        return []
    signals = signals or extract_signals(cv_text)
    terms = _signal_terms(signals)
    job_texts = [_job_text(j) for j in jobs]
    cosines = _cosine_scores(cv_text, job_texts)

    want_level = (risk_level or "").strip().capitalize() if risk_level else ""
    w_tfidf = config.CV_TFIDF_WEIGHT
    w_term = config.CV_TERM_WEIGHT
    total_w = (w_tfidf + w_term) or 1.0

    scored: list[dict[str, Any]] = []
    for job, jtext, cosine in zip(jobs, job_texts, cosines):
        level = (job.get("overall_risk_level") or "Low").capitalize()
        if exclude_risky and level in ("High", "Critical"):
            continue
        if want_level and level != want_level:
            continue

        nn = _norm(jtext)
        matched = [t for t in terms if _has_phrase(nn, t)]
        overlap = (len(matched) / len(terms)) if terms else 0.0
        if terms:
            blend = (w_tfidf * cosine + w_term * min(1.0, overlap)) / total_w
        else:
            blend = cosine
        fit = int(round(max(0.0, min(1.0, blend)) * 100))
        if fit < int(min_fit or 0):
            continue

        scored.append({
            "job_id": job.get("id"),
            "title": job.get("title") or "",
            "company": job.get("company") or "",
            "location": job.get("location") or "",
            "url": job.get("url") or "",
            "source": job.get("source") or "",
            "industry": job.get("industry") or "Other",
            "job_role": job.get("job_role") or "Other",
            "country": job.get("country") or "",
            "region": job.get("region") or "",
            "risk_level": level,
            "fit_score": fit,
            "matched_terms": matched[:12],
            "reason": _reason(matched, cosine),
            "_rank": fit - _risk_penalty(level),
        })

    scored.sort(key=lambda r: (-r["_rank"], -r["fit_score"]))
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 50
    for row in scored:
        row.pop("_rank", None)
    return scored[:limit]


def summarize(signals: dict[str, Any]) -> str:
    """One short, human-readable line describing the extracted CV signals."""
    return (
        f"Detected {len(signals.get('skills') or [])} skill(s), "
        f"{len(signals.get('tools') or [])} tool(s), "
        f"{len(signals.get('role_titles') or [])} likely role(s) "
        f"from {signals.get('word_count', 0)} words."
    )
