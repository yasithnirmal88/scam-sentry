# Yasith Nirmal Peiris — Evidence Index & Artifact Cross-Reference

**Student Name:** Yasith Nirmal Peiris  
**Registration Number:** D/BSE/25/0018  
**Group Number:** 44  
**Project Title:** Scam Sentry: An Intelligent Fake Job Advertisement Detection System  

This document serves as the master navigation index connecting each verified individual contribution to its corresponding repository artifacts, source files, Git commit hashes, and test verification evidence.

---

## Evidence Index Register

### [E01] Graded Risk Indicators Architecture
- **Supported Contribution:** `C01` — Graded Risk Hierarchy & Indicators (C1-C4, H1-H6, M1-M5, L1-L3).
- **Primary Source File:** [`fakejob_app/risk/indicators.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/risk/indicators.py)
- **Verified Commits:** `fe0abfd` (2026-10-10), `4cec4a1` (2026-10-10), `7cf880d` (2026-10-10)
- **Verification Evidence:** `tests/test_indicators.py` (6 tests passing), `tests/test_freshness.py` (14 tests passing).
- **Technical What-It-Demonstrates:** Implementation of 18 deterministic regex-backed risk indicators graded by severity, ensuring high precision red flag identification without probabilistic hallucination.

### [E02] First-Match-Wins Decision Tree & Safety Nets
- **Supported Contribution:** `C02` — Risk Determination Rules, Evidence Confidence, & Consistency Enforcement.
- **Primary Source Files:** [`fakejob_app/risk/engine.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/risk/engine.py), [`fakejob_app/risk/consistency.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/risk/consistency.py)
- **Verified Commits:** `fe0abfd` (2026-10-10), `4cec4a1` (2026-10-10), `0c191b8` (2026-10-12)
- **Verification Evidence:** `tests/test_engine.py` (17 tests passing), `tests/test_consistency.py` (6 tests passing), `tests/test_risk_floor.py` (2 tests passing).
- **Technical What-It-Demonstrates:** Ordered determination rules where Critical indicators unconditionally force a CRITICAL threat verdict, protected by V1-V3 safety nets preventing dilution by low-scoring components.

### [E03] Ethical Language Discipline & Forensic Reporting
- **Supported Contribution:** `C03` — Language Discipline Enforcement & Defamation Prevention.
- **Primary Source File:** [`fakejob_app/risk/language.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/risk/language.py)
- **Verified Commits:** `4cec4a1` (2026-10-10), `0c191b8` (2026-10-12)
- **Verification Evidence:** `tests/test_language.py` (5 tests passing).
- **Technical What-It-Demonstrates:** Lexical sweep that enforces academic and legal safety by prohibiting defamatory terms (e.g., "fake", "scam", "fraudulent") and substituting objective forensic evidence descriptions accompanied by legitimate explanations.

### [E04] Pluggable Scanner Framework & Source Connectors
- **Supported Contribution:** `C04` — Multi-Board Public Job Ingestion Engine.
- **Primary Source Files:** [`fakejob_app/scanner/base.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/scanner/base.py), [`fakejob_app/scanner/registry.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/scanner/registry.py), `fakejob_app/scanner/sources/*.py`
- **Verified Commits:** `4338d3e` (2026-10-10), `bb965f9` (2026-10-10), `5d6d4cb` (2026-10-12)
- **Verification Evidence:** `tests/test_scanners.py` (5 tests passing), `tests/test_new_scanners.py` (19 tests passing).
- **Technical What-It-Demonstrates:** Implementation of 10 autonomous job board scrapers (RemoteOK, Remotive, Arbeitnow, Jobicy, Himalayas, Working Nomads, LaraJobs, Greenhouse, Lever, Ashby) with SHA-256 URL hashing for deduplication.

### [E05] Background Scan Orchestration & Daemon Scheduler
- **Supported Contribution:** `C05` — Threading Daemon Scheduler & Scan Concurrency Management.
- **Primary Source Files:** [`fakejob_app/services/scheduler.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/services/scheduler.py), [`fakejob_app/services/scanner_service.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/services/scanner_service.py), [`fakejob_app/scan.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/scan.py)
- **Verified Commits:** `bb965f9` (2026-10-10), `b4fbaf5` (2026-10-16)
- **Verification Evidence:** `tests/test_phase3.py` (20 tests passing).
- **Technical What-It-Demonstrates:** Background daemon worker thread executing recurring cron-like job scans with mutex locking, asynchronous HTTP 202 endpoints, and CLI interface (`scan.py`).

### [E06] Dual-Engine Storage Facade & Migration Engine
- **Supported Contribution:** `C06` — Storage Abstraction for SQLite and PostgreSQL.
- **Primary Source Files:** [`fakejob_app/models/job.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/models/job.py), [`fakejob_app/models/storage.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/models/storage.py)
- **Verified Commits:** `4338d3e` (2026-10-10), `4e074a4` (2026-10-11), `0e09b6b` (2026-10-16)
- **Verification Evidence:** `tests/test_job_model.py` (17 tests passing across SQLite and real PostgreSQL).
- **Technical What-It-Demonstrates:** Repository design pattern abstracting raw SQL queries, supporting dynamic environment-based backend switching, automatic schema evolution, and location backfilling.

### [E07] API Security, Rate Limiting & Fail-Closed Guardrails
- **Supported Contribution:** `C07` — Audit Remediations F-01 to F-08 & Endpoint Hardening.
- **Primary Source Files:** [`fakejob_app/app.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/app.py), [`fakejob_app/config.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/config.py)
- **Verified Commits:** `1ec4d9c` (2026-10-11), `a122bde` (2026-10-11), `7ed03f4` (2026-10-13)
- **Verification Evidence:** `tests/test_abuse_control.py` (23 tests passing), `tests/test_scan_api.py` (22 tests passing).
- **Technical What-It-Demonstrates:** Industrial security hardening: token authentication (`X-Scan-Token`), IP sliding window rate limits, CSP/SAMEORIGIN headers, and fail-closed boot protection.

### [E08] ML Calibration & Hybrid Risk Safety Net
- **Supported Contribution:** `C08` — Scikit-learn Pipeline Calibration & Score Harmonization.
- **Primary Source Files:** [`fakejob_app/model_training.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/model_training.py), [`fakejob_app/app.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/app.py)
- **Verified Commits:** `0969ed9` (2026-10-11), `dfbc1db` (2026-10-11)
- **Verification Evidence:** `tests/test_ml_honesty.py` (14 tests passing), `tests/test_precision.py` (19 tests passing).
- **Technical What-It-Demonstrates:** Probability calibration of GradientBoosting synthetic model outputs and mathematical enforcement that ML scores cannot override rule-based risk floors.

### [E09] Industry & Job Role Taxonomy
- **Supported Contribution:** `C09` — Two-Tier Domain Categorization Engine.
- **Primary Source File:** [`fakejob_app/taxonomy.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/taxonomy.py)
- **Verified Commits:** `34238f1` (2026-10-11), `fba3fd1` (2026-10-12)
- **Verification Evidence:** `tests/test_taxonomy.py` (12 tests passing).
- **Technical What-It-Demonstrates:** 18 distinct industries and 100+ role regex definitions with negative lookarounds ensuring clean server-side filtering on the dashboard.

### [E10] Global Location Normalization & Bare-City Resolver
- **Supported Contribution:** `C10` — Geographic Normalization & City-to-Country Mapping.
- **Primary Source File:** [`fakejob_app/location.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/location.py)
- **Verified Commits:** `2366f41` (2026-10-16), `90e2e8e` (2026-10-16)
- **Verification Evidence:** `tests/test_location.py` (13 tests passing).
- **Technical What-It-Demonstrates:** Resolution of unstructured text into ISO country and regional entities, including a specialized lookup table mapping 80+ isolated global cities to their parent countries.

### [E11] Resume / CV Matching Pipeline
- **Supported Contribution:** `C11` — Candidate CV Relevance Analysis.
- **Primary Source Files:** [`fakejob_app/cv_matcher.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/cv_matcher.py), [`fakejob_app/cv_utils.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/cv_utils.py)
- **Verified Commits:** `cf8f90a` (2026-10-16), `65e6473` (2026-10-16), `5c8366c` (2026-10-16)
- **Verification Evidence:** `tests/test_cv_matcher.py` (10 tests passing), `tests/test_cv_api.py` (8 tests passing), `tests/test_cv_utils.py` (7 tests passing).
- **Technical What-It-Demonstrates:** Vectorization and cosine similarity scoring matching candidate resumes against ingested job postings while strictly avoiding risk verdict contamination.

### [E12] Dual-Mode Document OCR Pipeline
- **Supported Contribution:** `C12` — Robust Text & Image Document Extraction.
- **Primary Source Files:** [`fakejob_app/ocr_utils.py`](file:///d:/GitHub/Fake_job_detector/fakejob_app/ocr_utils.py), [`fakejob_app/Dockerfile`](file:///d:/GitHub/Fake_job_detector/fakejob_app/Dockerfile)
- **Verified Commits:** `7f6e3bd` (2026-10-16), `f5a7156` (2026-10-16)
- **Verification Evidence:** `tests/test_ocr_utils.py` (33 tests passing).
- **Technical What-It-Demonstrates:** Fast direct text extraction via `pdfplumber` with automatic fallback to Poppler/Tesseract OCR, hardened error handling, and Render Dockerfile system dependency packaging.

### [E13] Automated Test Suite & CI Matrix
- **Supported Contribution:** `C13` — Quality Assurance & Continuous Integration.
- **Primary Source Files:** `fakejob_app/tests/*` (31 files), [`.github/workflows/ci.yml`](file:///d:/GitHub/Fake_job_detector/.github/workflows/ci.yml)
- **Verified Commits:** `fe0abfd`, `0a66536`, `0c191b8`, `a9cdbd4` (all authored/merged by Yasith)
- **Verification Evidence:** 403 passed in 18.89s under pytest. CI runs `pyflakes .` and dual SQLite/Postgres matrix.
- **Technical What-It-Demonstrates:** Comprehensive automated verification covering edge cases, adversarial fuzzing, rate limit triggers, database migrations, and NLP robustness.
