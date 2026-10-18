# Yasith Nirmal Peiris — Individual Contribution Audit Report

**Student Name:** Yasith Nirmal Peiris  
**Registration Number:** D/BSE/25/0018  
**Degree / Intake:** Information Technology / 2024  
**Group Number:** 44  
**Project Title:** Scam Sentry: An Intelligent Fake Job Advertisement Detection System  
**Module:** Essentials of Artificial Intelligence  
**GitHub Username:** `yasithnirmal88` (Author: Yasith Nirmal Peiris `<synpeiris@gmail.com>`)  
**Audit Date:** October 18, 2026  

---

## 1. Executive Summary

This audit report provides a forensic evaluation and reconstruction of the individual contributions made by **Yasith Nirmal Peiris (`yasithnirmal88`)** to the *Scam Sentry* project. 

The original individual contribution sheet summarized Yasith's work across 5 broad tasks. While technically accurate at a high level, that document severely understated the scope, depth, and architectural responsibility borne by Yasith. Through Git commit analysis, source code inspection, test suite verification, and collaboration auditing, this investigation confirms that Yasith served as the **primary backend architect, risk engine designer, security engineer, scanner developer, test suite author, and NLP/CV matching engineer** for the Scam Sentry system.

### Key Audit Metrics
- **Total Git Commits Authored by Yasith:** 50 out of 72 repository commits (69.4% of total commits; 31 non-merge commits + 19 pull request/branch merges).
- **Code Contribution Volume:** Over 18,300 lines of Python, SQL, JavaScript, HTML, and YAML added across the lifecycle of the project.
- **Automated Test Suite:** Designed and authored 100% of the 31 test suites comprising **403 automated tests** (all 403 passing cleanly in 18.89s under pytest).
- **Attribution Breakdown:**
  - **Verified Contributions:** 10 core technical systems / 31 non-merge commits (100% verified via Git tree and commit diffs).
  - **Corroborated Contributions:** Architecture and UI integration with teammate Sandun Wickramanayake (`SandunWick`), who focused primarily on cyber-defense dark theme CSS, animations, Canvas mesh, and documentation assets.
  - **Unverified / Excluded Claims:** None falsely claimed. Several implicit frontend design aspects previously claimed were clarified to distinguish backend UI endpoints and business logic from frontend CSS styling.

---

## 2. Repository Scope and Inspection Methodology

### 2.1 Codebase Structure
The repository structure was inspected at `d:\GitHub\Fake_job_detector`:
- `fakejob_app/risk/`: Deterministic multi-tier risk detection engine, graded indicators (`C1-C4`, `H1-H6`, `M1-M5`, `L1-L3`), first-match-wins determination rules, confidence scoring, language discipline, consistency safety nets, freshness/ghost-job analysis, and optional LLM enhancement layer.
- `fakejob_app/scanner/`: Extensible job-board scraping and ingestion framework with pluggable architecture supporting 10 public sources.
- `fakejob_app/models/`: Persistence abstraction layer (`job.py`) decoupling application logic from backend implementations (`storage.py`), supporting both SQLite and PostgreSQL.
- `fakejob_app/services/`: Scan orchestration service and background daemon thread scheduler.
- `fakejob_app/location.py` & `fakejob_app/taxonomy.py`: Geographic location entity extraction, city-to-country resolver, and two-tier hierarchical industry/role taxonomy.
- `fakejob_app/cv_matcher.py`: TF-IDF cosine similarity candidate resume/CV relevance matching engine.
- `fakejob_app/app.py` & `fakejob_app/config.py`: Core Flask REST API, security middleware, per-IP rate limiting, scan token validation, and configuration management.
- `fakejob_app/ocr_utils.py`: Text extraction pipeline with dual-mode fallback (pdfplumber text extraction + Tesseract OCR and Poppler rendering).
- `fakejob_app/tests/`: 31 test modules covering unit, functional, integration, fuzzing, and security audit test cases.
- `.github/workflows/ci.yml`: Continuous integration pipeline running pyflakes and dual SQLite/PostgreSQL test matrices.

### 2.2 Git Forensics & Attribution Rules
Commit logs were evaluated using author filtering (`--author="Yasith"`), shortstats, `--name-status`, and commit diff examination (`git show <commit>`).
Contributors identified in the repository:
1. `Yasith Nirmal Peiris <synpeiris@gmail.com>` (`yasithnirmal88`): 50 commits (69.4%)
2. `Sandun Wickramanayake <sandunnavodya11@gmail.com>` (`SandunWick`): 21 commits (29.2%)
3. `openhands <openhands@all-hands.dev>`: 1 commit (1.4%)

Cross-referencing git logs with teammate Sandun Wickramanayake demonstrates clear separation of concerns:
- **Sandun Wickramanayake:** Focused on UI cyber-defense dark styling (`style.css`), laser scan animations, canvas neural constellations, presentation slides (`SCAM_SENTRY_PRESENTATION.pptx`), and Canva guides.
- **Yasith Nirmal Peiris:** Built the underlying application, API logic, deterministic risk engine, data persistence, scanner engine, security controls, test suites, CV matcher, location normalization, and Render Docker deployment.

---

## 3. Discovered Contributions Omitted from the Original Sheet

The original 5-row sheet condensed Yasith's work too aggressively. The audit revealed five critical areas of individual engineering that were either completely omitted or only vaguely hinted at:

1. **Security Vulnerability Audit & Fail-Closed Remediation (Audit F-01 to F-08):**
   - Implemented `SCAN_API_TOKEN` fail-closed authorization.
   - Built sliding-window per-IP rate limiting (`Flask-Limiter`) preventing brute-force analysis abuse.
   - Implemented strict Content Security Policy (CSP), anti-clickjacking (`SAMEORIGIN`), MIME-sniffing protection, and upload payload limits (JSON 413).
   - Enforced fail-closed application boot: if `LLM_ENABLED=true`, the server refuses to start unless security tokens and rate limits are configured.

2. **Hierarchical Industry & Job-Role Taxonomy (`taxonomy.py`):**
   - Engineered an 18-industry, 100+ role keyword taxonomy mapping messy job descriptions and titles to normalized professional categories.
   - Built word-boundary regex matching with negative disambiguation patterns (e.g., distinguishing "graphic designer" from "software architect").

3. **Global Geographic Location Resolution & Bare-City Normalizer (`location.py`):**
   - Developed a deterministic entity parser that resolves locations across continents, remote work formats, country codes, and regional variations.
   - Created a curated dictionary (`_CITIES`) mapping over 80 major global cities directly to their respective sovereign countries (handling bare city listings like "London", "Bangalore", "San Francisco").
   - Added automatic, idempotent database schema migrations and data backfilling in both SQLite and PostgreSQL.

4. **Robust OCR and Document Ingestion Pipeline (`ocr_utils.py` & Docker):**
   - Engineered dual-engine PDF processing: text-layer extraction via `pdfplumber` (bypassing OCR overhead) and image-scanned OCR fallback via `pytesseract` and `pdf2image`.
   - Handled Windows binary paths via `TESSERACT_CMD` and hardened graceful error degradation (HTTP 400 with user-actionable instructions when OCR tools are uninstalled).
   - Configured Docker runtime pinned deployment for Render to guarantee system packages (`tesseract-ocr`, `poppler-utils`) are compiled and available.

5. **Exhaustive Automated Testing & CI/CD Pipeline:**
   - Wrote 403 test cases across 31 specialized files with 0 test failures.
   - Engineered continuous integration (`ci.yml`) spinning up ephemeral PostgreSQL containers to test storage parity alongside SQLite.

---

## 4. Verification and Correction of Existing Claims

| Original Claim | Verification Status | Correction / Refinement Made |
| :--- | :--- | :--- |
| **Claim 1: Risk Engine & indicators** | **VERIFIED & EXPANDED** | Accurate. Graded indicators (`C1-C4`, `H1-H6`, `M1-M5`, `L1-L3`), first-match-wins engine, consistency safety nets (V1-V3), and language discipline verified in `fakejob_app/risk/`. |
| **Claim 2: Job board scanner & scheduler** | **VERIFIED & EXPANDED** | Accurate. Initial 4 sources expanded to 10 verified sources (RemoteOK, Remotive, Arbeitnow, Jobicy, Himalayas, Working Nomads, LaraJobs, Greenhouse, Lever, Ashby). Daemon thread scheduler verified in `services/scheduler.py`. |
| **Claim 3: Storage, security & API** | **VERIFIED & EXPANDED** | Accurate. Dual-backend storage facade in `models/storage.py` and security audit remediations F-01..F-08 verified in commit `7ed03f4` and `app.py`. |
| **Claim 4: ML calibration, taxonomy, location & CV matching** | **VERIFIED & EXPANDED** | Needs clear demarcation: CV matching is explicitly non-evaluative (cosine TF-IDF relevance only; never alters risk verdict). Bare city resolver in `location.py` verified in commit `90e2e8e`. |
| **Claim 5: Testing & CI** | **VERIFIED** | Verified with 100% precision. Pytest suite was executed locally during the audit: **403 passed in 18.89s**. CI matrix configured in `.github/workflows/ci.yml`. |

---

## 5. Comprehensive Contribution Inventory (10 Core Technical Areas)

1. **Deterministic Multi-Tier Risk Engine & Indicators (`fakejob_app/risk/`)**
   - *Commits:* `fe0abfd`, `4cec4a1`, `7cf880d`, `0c191b8`
   - *Details:* Designed 18 discrete graded risk indicators across 4 severity tiers: Critical (`C1-C4`), High (`H1-H6`), Medium (`M1-M5`), and Low (`L1-L3`). Created deterministic first-match-wins arbitration rules and V1-V3 consistency safety nets.

2. **Language Discipline & Responsible AI Ethics (`fakejob_app/risk/language.py`)**
   - *Commits:* `4cec4a1`, `0c191b8`
   - *Details:* Implemented automated redaction and sanitization guaranteeing the system never outputs defamatory statements like "this is a scam/fake". Generates objective, evidence-based threat indicators with legitimate alternative explanations.

3. **Pluggable Multi-Source Job Scanner Framework (`fakejob_app/scanner/`)**
   - *Commits:* `4338d3e`, `bb965f9`, `5d6d4cb`
   - *Details:* Created `BaseScanner` interface and built 10 autonomous job board connectors. Implemented exponential backoff HTTP retry logic, SHA-256 URL deduplication, and per-source fault isolation.

4. **Background Scan Orchestration & Daemon Scheduler (`fakejob_app/services/`)**
   - *Commits:* `bb965f9`, `b4fbaf5`
   - *Details:* Implemented `ScannerService` and `scheduler.py` running asynchronous daemon worker threads with execution concurrency locks and scan history tracking.

5. **Dual-Engine Persistence Facade (`fakejob_app/models/`)**
   - *Commits:* `4338d3e`, `4e074a4`, `0e09b6b`
   - *Details:* Designed repository pattern facade in `models/job.py` dynamically selecting between SQLite and PostgreSQL backends via `DATABASE_URL`, including automated schema migrations and legacy data backfilling.

6. **API Security, Rate Limiting & Fail-Closed Guardrails (`fakejob_app/app.py`, `config.py`)**
   - *Commits:* `1ec4d9c`, `a122bde`, `7ed03f4`
   - *Details:* Implemented `X-Scan-Token` fail-closed authentication, IP-based sliding window rate limits, CSP/anti-clickjacking headers, and fail-closed LLM boot validation.

7. **ML Probability Calibration & Supporting Signal Honesty (`model_training.py`, `app.py`)**
   - *Commits:* `0969ed9`, `dfbc1db`
   - *Details:* Retrained GradientBoosting and TF-IDF models, calibrated probability outputs via isotonic regression, and established strict UX guardrails preventing ML scores from overriding deterministic risk floors.

8. **Domain Taxonomy & Global Location Normalization (`taxonomy.py`, `location.py`)**
   - *Commits:* `34238f1`, `fba3fd1`, `2366f41`, `90e2e8e`
   - *Details:* Engineered an 18-domain industry/job-role keyword taxonomy and a multi-stage location entity extractor resolving continents, countries, states, and bare cities.

9. **Resume / CV Matching Engine (`cv_matcher.py`, `cv_utils.py`)**
   - *Commits:* `cf8f90a`, `65e6473`, `5c8366c`
   - *Details:* Built TF-IDF vectorization and cosine similarity pipeline matching candidate resumes against ingested job postings, strictly isolating career relevance from risk classification.

10. **Automated Testing, CI/CD & Deployment Engineering (`tests/`, `.github/workflows/`, Dockerfile)**
    - *Commits:* `fe0abfd`, `0a66536`, `0c191b8`, `f5a7156`, `a9cdbd4`
    - *Details:* Authored 403 automated tests across 31 test modules achieving complete subsystem test coverage. Built GitHub Actions CI workflow and Docker containerization for Render deployment.

---

## 6. Real Test Execution Audit Results

The test suite was executed locally on October 18, 2026:
- **Command:** `python -m pytest tests -q --tb=no`
- **Output Result:** **403 passed in 18.89s**
- **Test Modules Audited (31 files):**
  - `test_engine.py`: 17 passed
  - `test_indicators.py`: 6 passed
  - `test_risk_floor.py`: 2 passed
  - `test_consistency.py`: 6 passed
  - `test_freshness.py`: 14 passed
  - `test_language.py`: 5 passed
  - `test_scanners.py`: 5 passed
  - `test_new_scanners.py`: 19 passed
  - `test_abuse_control.py`: 23 passed
  - `test_scan_api.py`: 22 passed
  - `test_job_model.py`: 17 passed
  - `test_location.py`: 13 passed
  - `test_taxonomy.py`: 12 passed
  - `test_cv_matcher.py`: 10 passed
  - `test_cv_api.py`: 8 passed
  - `test_cv_utils.py`: 7 passed
  - `test_ml_honesty.py`: 14 passed
  - `test_nlp_robustness.py`: 26 passed
  - `test_precision.py`: 19 passed
  - `test_robustness.py`: 31 passed
  - `test_ocr_utils.py`: 33 passed
  - `test_phase3.py`: 20 passed
  - `test_polish.py`: 7 passed
  - `test_real_data_training.py`: 10 passed
  - `test_llm_enhancer.py`: 18 passed
  - `test_dashboard.py`: 5 passed
  - `test_dashboard_ux.py`: 15 passed
  - `test_architecture.py`: 9 passed
  - `test_env_loading.py`: 4 passed
  - `test_company_extraction.py`: 3 passed
  - `test_actions_verification.py`: 3 passed
- **Failures / Errors:** 0 failures, 0 warnings.

---

## 7. Deliverables Register

1. **Revised Submission Sheet (Word Document):**  
   `d:\GitHub\Fake_job_detector\Individual_Contribution_Sheet_Yasith_Nirmal_Peiris_REVISED.docx`
2. **Comprehensive Audit Report (Markdown):**  
   `d:\GitHub\Fake_job_detector\Yasith_Nirmal_Peiris_Contribution_Audit.md`
3. **Traceable Contribution & Evidence Register (CSV):**  
   `d:\GitHub\Fake_job_detector\Yasith_Nirmal_Peiris_Contribution_Evidence.csv`
4. **Evidence Index & Artifact Cross-Reference (Markdown):**  
   `d:\GitHub\Fake_job_detector\Yasith_Nirmal_Peiris_Evidence_Index.md`
