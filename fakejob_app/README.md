# Scam Sentry — Job Risk Scanner

Scam Sentry protects job seekers from employment scams. It works two ways:

1. **Single-job analysis** — paste an ad (or upload a PDF/image) and get an
   explainable risk assessment in seconds.
2. **Job Risk Scanner** — automatically pulls live listings from public job
   boards, evaluates each one with the same Risk Engine, and presents them
   in a dashboard grouped by risk level.

It never claims a posting is "a scam" or "fake". It reports **risk levels
with evidence** (🚨 Critical · 🔴 High · 🟡 Medium · 🟢 Low) plus concrete
next steps.

## How risk levels work (short version)

- Each posting is checked against graded indicators: **C1–C4** (critical:
  fees, sensitive-data requests, guaranteed-income pressure, known scam
  patterns), **H1–H5** (high: free email, urgency, missing company, domain
  mismatch, ghost/stale), **H6** (medium: non-English/unverifiable content),
  **M1–M5** (medium, incl. aging listings), **L1–L3** (low/weak).
- **First match wins, top-down**: any Critical → Critical; ≥2 High (or
  1 High + ≥2 Medium) → High; 1 High or ≥2 Medium → Medium; only weak
  signals or nothing → Low.
- **Criticals always dominate**: one Critical indicator forces Critical and
  floors the hybrid score, so the ML side can never average it away.
  Freshness/staleness adds context but can never override a Critical.
- **Confidence** reflects evidence strength (multiple strong signals →
  High; partial → Medium; weak-only → Low), and every summary allows a
  legitimate alternative explanation. A deterministic safety net
  re-checks each verdict (Critical floor, impersonation pair, wording).

## What Scam Sentry does NOT do

- No absolute fake/real verdicts — only evidence-backed risk levels.
- No LinkedIn scraping and no authenticated or paywalled sources. Automatic
  scanners use public, no-auth endpoints only; LinkedIn is manual analysis
  only (paste/upload).
- No browser automation — liveness is inferred from posting dates and
  wording, not live page checks.
- No accounts, no email alerts, no auto-applying — it never acts on your behalf.
- No hireability guarantee. CV matching ranks *relevance* to your CV; it does
  not predict whether you will be hired, and it is not an ATS score.

## How it works

- **Risk Engine** (`risk/`): severity-graded indicators (C1–C4 critical,
  H1–H5 high, H6 + M1–M5 medium, L1–L3 low) → first-match-wins determination
  rules → confidence, categories, summary, recommended actions, and a
  lightweight employer check. A Critical indicator always forces Critical,
  regardless of the ML score.
- **Hybrid scoring**: transparent rule score blended with a
  `GradientBoostingClassifier` (TF-IDF + engineered fraud features) as a
  supporting signal — never a black box.
- **Scanners** (`scanner/`): ten automatic sources — RemoteOK, Remotive,
  Arbeitnow, Jobicy, Himalayas, Working Nomads, LaraJobs, Greenhouse, Lever,
  Ashby. Every automatic scanner reads a **public, no-auth** JSON/RSS endpoint
  (no keys, OAuth, cookies, login, or browser automation). Modular
  `BaseScanner` + registry — adding a source is one subclass. LinkedIn is
  **manual analysis only** (paste/upload) and is never bulk-scraped.
- **Storage** (`models/job.py` + `models/storage.py`): SQLite by default;
  when `DATABASE_URL` is set, the same public API runs on Postgres (Render /
  Neon / Supabase free tier). Jobs upsert by normalized URL and every scan is
  recorded in `scan_history`. **Deploy note:** on Render's free tier the disk
  is ephemeral — the local SQLite file (and all scan history) is wiped on
  every deploy or restart. Set `DATABASE_URL` for durable storage.
- **Scheduler** (`services/scheduler.py`): dependency-free background thread,
  every N hours; manual scans also run async so the web app never blocks.

## Indicator systems: who decides the verdict

There are two rule/indicator systems, and their roles are deliberately split:

- **`risk/indicators.py` + `risk/engine.py` — authoritative decisioning.**
  These produce the graded indicators (C1–C4, H1–H6, M1–M5, L1–L3) and the
  **overall risk level**, risk categories, key indicators, and recommended
  actions. This is the single source of truth for the verdict.
- **`fraud_features.py` — ML feature support.** It extracts legacy engineered
  features that feed the TF-IDF + GradientBoosting hybrid score and provides a
  transparent rule score. That hybrid score is a **supporting signal only**
  (reported as `hybrid_score` / `prediction` / `risk_level` for backward
  compatibility); it never overrides or contradicts the Risk Engine. The
  authoritative level is reported as `overall_risk_level`.

To keep the two consistent instead of divergent, the signal primitives they
share — text normalization (`normalize`), the pattern banks, `extract_company_name`,
and the company/domain matcher (`company_matches_domain`) — live in
`fraud_features.py` and are imported by the Risk Engine, so H4 and the legacy
`suspicious_url` feature agree on what a company/domain mismatch is.

**Robustness of the text matching.** Indicator wording is paraphrase-tolerant
and negation-aware without loosening the Critical rules:

- Pattern banks match common rewordings of the same behavior (e.g. "onboarding
  fee", "good-faith deposit", "share your banking details") alongside the
  literal phrasing.
- C1/C2 (Critical) skip a match whose request is *negated within its clause*
  ("there is no registration fee", "we never ask for your bank account
  number"), so disclaimers do not read as scams — while a fee in a *different*
  clause still fires ("no experience needed. A $20 registration fee applies").
- A limited set of high-signal non-English fee/credential phrases
  (ES/FR/DE/PT/ID/TL) is recognized, and predominantly non-Latin-script
  postings raise **H6** (Medium) instead of returning a misleading confident
  "Low". H6 is a confidence caveat, never evidence of fraud by itself.

## Optional LLM enhancement layer

Scam Sentry works fully without any LLM. When `LLM_ENABLED=true`, a thin
optional layer (`risk/llm_enhancer.py`) calls an **OpenAI-compatible**
`chat/completions` endpoint to rewrite the summary in clearer language and
add a short reasoning note.

Design guarantees:

- **The Risk Engine stays the source of truth.** The LLM never decides or
  changes the risk level, and can never downgrade a Critical result — any
  output that would soften Critical risk is rejected.
- **Same language discipline.** Output containing banned conclusion
  phrasing ("this is a scam" / "this is fake") is rejected; the engine's own
  summary is kept instead.
- **Graceful fallback.** Disabled by default; a strict timeout plus total
  exception isolation means a missing/unreachable/erroring provider changes
  nothing — analysis continues with the engine output.
- **Zero-token scanning by default.** Automatic scanner runs skip the LLM
  unless `LLM_SCANNER_ENABLED=true`; enhancement targets on-demand
  single-job analysis.

The response adds `llm_enhanced` (bool), `llm_model`, `llm_explanation`, and
`engine_summary` (the untouched engine summary). Set it up in `.env`:

```bash
export LLM_ENABLED=true
export LLM_BASE_URL=https://openrouter.ai/api/v1   # or OpenAI, Groq, Ollama /v1
export LLM_API_KEY=sk-...                           # not needed for local Ollama
export LLM_MODEL=gpt-4o-mini
```

## Features

- Paste-text / file-upload (PDF, PNG, JPG) analysis with OCR
- Risk dashboard (`/dashboard`): grouped by risk level, counts, filters
  (risk / source / keyword search), job detail pages with full evidence
- **Search by Industry & Job Role**: two dashboard sections listing the world's
  industry categories and the job roles under each. Every scanned listing is
  auto-classified into industry + role (deterministic keyword rules in
  `taxonomy.py`; display/filter aid only, never part of the risk verdict), and
  the detail page shows both chips. Filter by industry, then narrow to a role.
- **Search by Country / Region**: a dashboard row filters listings by country
  (plus a remote / on-site toggle). Each listing's free-text `location` is
  normalized on save (best-effort, rules in `location.py`; display/filter aid
  only, never part of the risk verdict) into a country + region. Filters are
  applied server-side via `/api/jobs?country=&region=&remote=`.
- **CV-based job matching** (`/dashboard` panel or `POST /api/match/cv`):
  upload a CV (PDF / TXT / DOCX) or paste its text, and the scanned jobs are
  ranked by relevance — each result still shows the Risk Engine's safety level.
  See [CV job matching](#cv-job-matching).
- One-click scans from the UI, background scheduler, `scan.py` CLI
- Optional LLM enhancement layer (OpenAI-compatible; off by default)
- 390+ automated tests (`pytest`)

## Running it locally

### 1. System dependencies (OCR only; skip if you only use paste-text + scanner)

Tesseract (image/scanned-PDF text) and Poppler (PDF rasterizing) are **system**
binaries — `pip` does not install them. Everything except image/scanned-PDF
upload works without them.

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr poppler-utils
# macOS
brew install tesseract poppler
# Windows (winget)
winget install UB-Mannheim.TesseractOCR          # then install Poppler
```

On Windows the Tesseract installer is usually not on `PATH`; the app probes the
default `C:\Program Files\Tesseract-OCR\tesseract.exe` automatically. For a
custom location set `TESSERACT_CMD=C:\path\to\tesseract.exe` (see
[Environment variables](#environment-variables)).

| Works **without** OCR | Needs OCR (Tesseract) |
|---|---|
| Paste-text analysis | Uploaded screenshots / photos (`.png/.jpg/.jpeg`) |
| Uploaded **text-based** PDFs (text layer extracted via pdfplumber) | **Scanned** PDFs with no text layer |
| Scanner + dashboard | — |

When the OCR engine is missing, an image/scanned-PDF upload returns a clear
`400` ("OCR is unavailable on this server… paste the job text…") instead of a
stack trace; text paste and text-based PDFs keep working.

### 2. Python setup

```bash
cd fakejob_app
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

Open **http://localhost:5000** (analyzer) and
**http://localhost:5000/dashboard** (scanner dashboard).

On first run the model trains automatically (a few seconds, balanced
synthetic data) and is saved to `artifacts/`. With `SCAN_ENABLED=false`
(default) no network scanning happens until you trigger one.

To retrain explicitly (and see hold-out metrics), run
`python model_training.py`; add `--real fake_job_postings.csv` to train on the
EMSCAD/Kaggle dataset if you have it. See **ML honesty** below.

### Local dashboard scanning

`POST /api/scan` is fail-closed and the dashboard sends **no** token, so a fresh
clone cannot trigger a scan until you opt in. The easiest local/demo path is to
copy the sample env file and restart the app (it auto-loads `.env` on start):

```bash
cp .env.example .env            # Windows: copy .env.example .env
```

`.env.example` ships the local/demo setup — `SCAN_ALLOW_ANONYMOUS=true` with an
empty `SCAN_API_TOKEN` — so the dashboard **Run Scan** button works. A local
`.env` only supplies values that are *not already set* in your environment
(exported variables always win); set `SCAM_SENTRY_NO_DOTENV=true` to ignore
`.env` entirely.

For programmatic use, set `SCAN_API_TOKEN=<long random>` instead and send it in
the `X-Scan-Token` header:

```bash
curl -X POST http://localhost:5000/api/scan \
  -H "Content-Type: application/json" \
  -H "X-Scan-Token: $SCAN_API_TOKEN" \
  -d '{"sources": ["remotive"], "limit": 10}'
```

A configured token always wins over `SCAN_ALLOW_ANONYMOUS`, so the dashboard
(token-free) trigger stays rejected while the API works.

### Production (gunicorn)

```bash
gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 120 app:app
```

Or with Docker (runs as the non-root `appuser`, ships a `/api/health`
`HEALTHCHECK`, and keeps the SQLite DB on the `/data` volume):

```bash
cd fakejob_app
docker build -t scam-sentry .
docker run -p 5000:5000 -e SCAN_ENABLED=true -v scam-sentry-data:/data scam-sentry
```

The image defaults `SCAM_SENTRY_DB=/data/scam_sentry.db`; omit the `-v` volume
for an ephemeral DB, or pass `-e DATABASE_URL=...` to use Postgres instead.

## Running a scan

- **UI**: open `/dashboard`, pick sources, click **Run New Scan**
  (progress + auto-refresh; safe to leave the page).
- **API**: `POST /api/scan` → `202` (async); poll `GET /api/scan/status`.
  Add `?sync=1` to wait for completion. This endpoint is fail-closed: send a
  matching `X-Scan-Token` header, or set `SCAN_ALLOW_ANONYMOUS=true` for a
  local demo (see [Abuse & cost control](#abuse--cost-control)).
- **CLI** (cron-friendly): `python scan.py --sources remotive jobicy --limit 10`
  - Cron example (every 6 hours):
    `0 */6 * * * cd /path/to/fakejob_app && python scan.py >> scan.log 2>&1`
  - `python scan.py --daemon` runs the interval loop; `--list-sources` lists sources.

## Enabling the scheduler

```bash
export SCAN_ENABLED=true
export SCAN_INTERVAL_HOURS=6   # default
export SCAN_SOURCES="remotive,jobicy"  # empty = all sources
python app.py
```

The first scan starts ~5s after boot, then repeats on the interval. The
scheduler never blocks the web app, and only one scan runs at a time
(concurrent triggers get HTTP 409). See `.env.example` for all settings.

## Available sources

All automatic scanners use **public, no-auth, read-only** endpoints — no API
keys, OAuth, cookies, logins, or browser automation. Ten sources are active:

| Source | Auth | Type | Status |
|---|---|---|---|
| RemoteOK | none | Public JSON API | active |
| Remotive | none | Public JSON API | active |
| Arbeitnow | none | Public JSON API | active |
| Jobicy | none | Public JSON API | active |
| Himalayas | none | Public JSON API | active |
| Working Nomads | none | Public JSON API | active |
| LaraJobs | none | Public RSS feed | active |
| Greenhouse | none | Public company-board JSON | active |
| Lever | none | Public company-board JSON | active |
| Ashby | none | Public company-board JSON | active |

`GET /api/sources` returns the live list; the dashboard's source filter,
`SCAN_SOURCES`, and `python scan.py --list-sources` all use these same names.

### Endpoints & limitations

| Source | Endpoint | Response | Key fields | Notes |
|---|---|---|---|---|
| RemoteOK | `https://remoteok.com/api` | JSON array | position, company, description, url, epoch | first element is legal metadata (skipped) |
| Remotive | `https://remotive.com/api/remote-jobs` | JSON object | title, company_name, candidate_required_location, description, url, publication_date | honors `?limit=` |
| Arbeitnow | `https://arbeitnow.com/api/job-board-api` | JSON object | title, company_name, location, description, url, created_at | |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs` | JSON object | jobTitle, companyName, jobGeo, jobDescription, url, pubDate | `?count=` |
| Himalayas | `https://himalayas.app/jobs/api` | JSON object | title, companyName, locationRestrictions, description, applicationLink, pubDate | `?limit=`; cursor pagination available |
| Working Nomads | `https://www.workingnomads.com/api/exposed_jobs/` | JSON array | title, company_name, location, description, url, pub_date | can be slow; per-source timeout floor |
| LaraJobs | `https://larajobs.com/feed` | RSS 2.0 | title, link, company, location, content:encoded, pubDate | namespace-agnostic parse |
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | JSON object | title, company_name, location.name, content, absolute_url, first_published | walks `GREENHOUSE_BOARDS`; `content` is HTML-escaped |
| Lever | `https://api.lever.co/v0/postings/{board}?mode=json` | JSON array | text, categories.location, descriptionPlain, hostedUrl, createdAt | walks `LEVER_BOARDS` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{board}` | JSON object | title, location, isRemote, publishedAt, jobUrl, descriptionPlain | walks `ASHBY_BOARDS` |

The Greenhouse/Lever/Ashby vendors expose only **per-company** boards (no
global feed), so each board-scanner walks a configurable list of public board
tokens — `GREENHOUSE_BOARDS`, `LEVER_BOARDS`, `ASHBY_BOARDS` (comma-separated,
env-overridable; `SCANNER_MAX_BOARDS` caps how many are fetched per run). A
board that fails is skipped and logged without aborting the scan.

### Why no LinkedIn (and other skipped sources)

- **LinkedIn is manual analysis only** — paste or upload a single posting into
  the analyzer. It is **never** bulk-scraped: LinkedIn's terms prohibit
  automated scraping, its listings require login, and there is no no-auth
  public jobs API, so an automatic scanner would need cookies/browser
  automation, which this project rejects.
- Sources evaluated and skipped because they need credentials or block
  scripted no-auth access (they fail the "public, no-auth, stable" test):
  USAJobs (requires an API key), The Muse (blocked without a key in practice),
  We Work Remotely RSS (403 to non-browser clients), SmartRecruiters public
  boards (return empty results for public tokens), and feeds that now require
  a key (e.g. Adzuna, Jooble, Reed, Findwork). A source is added only when it
  is reliably reachable with **no** authentication.

## API overview

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analyze/text` | POST `{"text": "..."}` | Single-job risk report |
| `/api/analyze/file` | POST multipart `file` | Single-job risk report (OCR) |
| `/api/jobs?risk_level=&source=&industry=&role=&country=&region=&remote=&q=&limit=&offset=` | GET | Scanned jobs + per-level counts (`industry`/`role` filter by the auto-classified taxonomy fields; `country`/`region` match the normalized location — country aliases like `USA`/`UK` resolve to their canonical name; `remote=true|false` toggles remote/worldwide vs on-site). The response also carries `countries` and `regions` picker options (global, unaffected by the current filters). `total` is the count matching the current filters; `global_total` is the unfiltered count across all sources |
| `/api/jobs/<id>` | GET | One stored job with full risk report |
| `/api/match/cv` | POST multipart `file` (PDF/TXT/DOCX) **or** JSON `{"cv_text": "..."}` | Rank stored jobs by relevance to a CV. Optional filters: `min_fit` (0-100), `risk_level`, `exclude_risky` (drop High+Critical), `source`, `industry`, `role`, `country`, `region`, `remote`, `limit`. Returns extracted CV signals + ranked `matches` (each with `fit_score`, `matched_terms`, `reason`, and the job's unchanged engine `risk_level`). Relevance only — never a risk verdict |
| `/api/scan` | POST `{"sources": [...], "limit": N}` + `X-Scan-Token` header | Async scan → `202`; `?sync=1` to wait. `401` without a valid `SCAN_API_TOKEN`, `429` when over the rate limit |
| `/api/scan/status` | GET | Running/idle + last recorded run |
| `/api/scan/history?limit=` | GET | Recent scan runs, newest first (id, status, stored/fetched/skipped/duplicates, sources) — rendered on the dashboard |
| `/api/sources` | GET | Registered scanner names |
| `/api/taxonomy` | GET | World industry categories + the job roles under each (powers the dashboard's industry/role pickers) |
| `/api/health` | GET | `{"status": "ok", "model_loaded": false, "model": {...}}` — `model_loaded` flips to `true` after the first `/api/analyze` (the ML model loads lazily); `model` is the model card (source/estimator/samples/accuracy) |

## CV job matching

CV matching answers a **different question** from the Risk Engine:

- **Risk Engine** → *is this posting safe?* (authoritative; stored per job).
- **CV Matcher** → *is this posting relevant to this candidate?*

The matcher only ranks jobs that are **already stored** by the scanner; it needs
no live source and never changes a risk level. It lives in `cv_matcher.py`
(scoring) and `cv_utils.py` (text extraction), and is exposed as the
"🎯 Match Jobs to Your CV" panel on the dashboard and as `POST /api/match/cv`.

**Supported inputs.** `.pdf` (text layer, with OCR fallback for scanned PDFs —
reusing `ocr_utils`), `.txt`, and `.docx` (parsed with the standard library, no
extra dependency). Uploads are capped at 10 MB and restricted to that
allowlist; the CV is processed in-request and **never stored**. You can also
paste CV text instead of uploading a file.

### How a match score is built (transparent, no deep learning)

1. **Signal extraction** — the CV text is scanned for a curated skill/tool
   vocabulary (explicit `matched_terms`), role titles (reusing `taxonomy.py`),
  frequent keywords, and simple section headings (`skills`, `experience`, …).
- **TF-IDF + cosine similarity** measures overall wording similarity between
  the CV and each job's title/role/description.
- A **blended score** `0-100` combines the two
  (`CV_TFIDF_WEIGHT` × cosine + `CV_TERM_WEIGHT` × term-overlap, both defaults
  in `config.py`).

Each result carries `fit_score`, `matched_terms`, a short human `reason`, and
the job's **unchanged** `risk_level`. Default ordering is fit-first with a
safety preference: higher `fit_score` ranks higher, but **Critical postings are
pushed to the very bottom** and are never a top recommendation. The dashboard
panel hides High/Critical matches by default (`exclude_risky`).

Example request/response:

```bash
curl -X POST https://<host>/api/match/cv \
  -F "file=@my_cv.pdf" -F "min_fit=20" -F "exclude_risky=1"
```

```json
{
  "cv": {"summary": "Detected 3 skill(s), 5 tool(s), 1 likely role(s) from 42 words.",
         "tools": ["aws", "django", "docker", "postgresql", "python"],
         "skills": [], "role_titles": ["Software Engineer"],
         "keywords": ["python", "backend", "..."], "sections": ["skills"]},
  "matches": [
    {"job_id": 12, "title": "Python Backend Engineer", "company": "Acme",
     "location": "Berlin, Germany", "source": "remoteok",
     "risk_level": "Low", "fit_score": 71,
     "matched_terms": ["python", "django", "postgresql", "docker", "aws"],
     "reason": "Matches your CV on: python, django, postgresql, docker, aws."}
  ],
  "total_matches": 1, "candidate_jobs": 240,
  "disclaimer": "Relevance matching only -- it ranks scanned jobs by fit ..."}

### Design rules & limitations

- **Never a risk verdict.** Matching copies the engine's `risk_level` through
  unchanged; it can never upgrade or downgrade a job's safety.
- **Never a guarantee.** The `disclaimer` field and UI state plainly that a
  high fit score is relevance, *not* a promise of suitability or hireability.
- **Critical is never a top recommendation.** Critical listings are ranked
  last by default and can be excluded entirely with `exclude_risky`.
- **No CV is stored.** Text is extracted and scored in-request; nothing is
  persisted and no candidate profile/account is required.
- **No LLM involvement.** CV text is never sent to the optional LLM layer.
- Practical, not perfect: signals come from a curated keyword vocabulary plus
  TF-IDF, so unusual formats/titles or very short CVs will match less well.

## Environment variables

See `.env.example`. The app auto-loads a local `.env` (via python-dotenv) at
startup; exported environment variables always take precedence, and
`SCAM_SENTRY_NO_DOTENV=true` disables the file entirely. Highlights:

| Variable | Default | Meaning |
|---|---|---|
| `FLASK_HOST` / `FLASK_PORT` | `0.0.0.0` / `5000` | Server bind |
| `FLASK_DEBUG` | `false` | Never enable in production |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SCAM_SENTRY_DB` | `scam_sentry.db` | SQLite file |
| `SCAM_SENTRY_NO_DOTENV` | `false` | When `true`/`1`, ignore a local `.env` and read only real environment variables |
| `TESSERACT_CMD` | *(empty)* | Absolute path to the Tesseract binary when it is not on `PATH` (e.g. a custom Windows install). Empty = resolve from `PATH`, then the default Windows location |
| `OCR_MAX_PDF_PAGES` / `OCR_PDF_DPI` / `OCR_MAX_IMAGE_PIXELS` | `5` / `150` / `20000000` | Upload/OCR hard caps (pages read, raster DPI, pixel budget) |
| `DATABASE_URL` | *(empty)* | Postgres connection string. When set, it takes precedence over the SQLite file (Render/Neon/Supabase). Leave empty for local SQLite |
| `SCAN_API_TOKEN` | *(empty)* | Shared secret required by `POST /api/scan` (sent in the `X-Scan-Token` header). Empty = fail-closed: the endpoint rejects every request unless `SCAN_ALLOW_ANONYMOUS=true` |
| `SCAN_ALLOW_ANONYMOUS` | `false` | Dev/demo only: allow unauthenticated scans when `SCAN_API_TOKEN` is empty. Ignored when a token is set; never enable on a public deployment |
| `RATE_LIMIT_ANALYZE` | `30/minute` | Per-IP rate limit on `/api/analyze/*` (Flask-Limiter syntax) |
| `RATE_LIMIT_SCAN` | `5/minute` | Per-IP rate limit on `POST /api/scan` |
| `RATE_LIMIT_READ` | `240/minute` | Per-IP rate limit on the public read endpoints (`/api/jobs*`, `/api/scan/status`, `/api/scan/history`, `/api/sources`, `/api/taxonomy`, `/dashboard*`) |
| `TRUSTED_PROXY_HOPS` | `1` | Number of reverse-proxy hops trusted for `X-Forwarded-For` when resolving the client IP (rate-limit identity). `1` fits Render's single proxy; set `0` when exposed directly |
| `SCAN_ENABLED` | `false` | Background scheduler on/off |
| `SCAN_INTERVAL_HOURS` | `6` | Scheduler interval |
| `SCAN_RUN_ON_STARTUP` | `true` | First scan shortly after boot |
| `SCAN_SOURCES` | *(all)* | Comma-separated source subset |
| `SCAN_LIMIT` | `20` | Jobs per source (1–100) |
| `SCANNER_TIMEOUT` / `SCANNER_RETRIES` / `SCANNER_RETRY_BACKOFF` | `20` / `2` / `2` | HTTP reliability |
| `LLM_ENABLED` | `false` | Optional LLM enhancement layer |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI defaults | OpenAI-compatible endpoint |
| `LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_TEMPERATURE` | `12` / `400` / `0.2` | LLM request controls |
| `LLM_SCANNER_ENABLED` | `false` | Also enhance automatically-scanned listings |
| `ML_CALIBRATION` | `true` | Shrink the ML probability toward a neutral prior |
| `ML_CALIBRATION_PRIOR` / `ML_CALIBRATION_SHRINK` | `0.5` / `0.7` | Calibration parameters |

## Abuse & cost control

- **Scan trigger is fail-closed by default.** `POST /api/scan` requires an
  `X-Scan-Token` header whose value matches `SCAN_API_TOKEN` — otherwise `401`.
  With the token left **empty** the endpoint still rejects every request unless
  you explicitly opt into anonymous scans with `SCAN_ALLOW_ANONYMOUS=true`
  (dev/demo only). The anonymous flag is ignored when a token is set, and the
  fail-closed startup guard still refuses to boot with `LLM_ENABLED=true`
  without a token — so a spend-enabled server can never run open.
- **Enabling anonymous scans for a local demo:** set
  `SCAN_ALLOW_ANONYMOUS=true` (and leave `SCAN_API_TOKEN` empty). The dashboard
  sends no token (there is no token UI), so this is the intended way to click
  **Run New Scan** locally; without it the dashboard shows the server's `401`
  message. Never enable the flag on a public deployment — set a token instead.
- **Per-IP rate limiting** on the costliest endpoints (`/api/analyze/text`,
  `/api/analyze/file`, and `/api/scan`) via Flask-Limiter. Defaults:
  `RATE_LIMIT_ANALYZE=30/minute`, `RATE_LIMIT_SCAN=5/minute`; over the limit
  the API answers `429` with a JSON error. Counters live in process memory
  (per worker on a multi-worker gunicorn).
- **Read endpoints are lightly limited** (`RATE_LIMIT_READ=240/minute`) so bulk
  scraping is blunted without throttling normal use. The limit is applied to
  `/api/jobs`, `/api/jobs/<id>`, `/api/scan/status`, `/api/scan/history`,
  `/api/sources`, `/api/taxonomy`, and the `/dashboard` pages, and is set well
  above the write limits so live scan polling is never throttled.
- **Real client IP behind a proxy.** `TRUSTED_PROXY_HOPS` (default `1`) wraps
  the app in Werkzeug's `ProxyFix` so `request.remote_addr` — and the limiter's
  identity — is the real client from `X-Forwarded-For` rather than the proxy.
  Set it to `0` when the app is exposed directly (no proxy) so a spoofed
  `X-Forwarded-For` cannot evade the limiter; local dev needs no change.
- **Content-Security-Policy** is sent on every response (`default-src 'self'`,
  static JS/CSS same-origin, Google Fonts allowed for the styled pages).
- **Fail-closed LLM startup:** with `LLM_ENABLED=true` (the only path that
  spends money / sends text off-box), the app refuses to start unless
  `SCAN_API_TOKEN` *and* both rate limits are configured. Set them first.

## ML honesty

### What the ML model contributes

The ML classifier is a **supporting signal only**. It adds a calibrated
probability that nudges the **hybrid score** used for ranking/display, and it
contributes a score floor for clearly critical text. It does **not** decide the
verdict: the deterministic **Risk Engine** (`risk/`) sets
`overall_risk_level`, `risk_categories`, `key_indicators`, and
`recommended_actions`. ML can never raise a non-critical post to Critical on its
own, and it can never lower a Critical Risk Engine decision.

### Default training is synthetic

Out of the box the model is a **GradientBoosting classifier trained on a
balanced synthetic dataset** generated by `model_training.py`. The EMSCAD /
Kaggle `fake_job_postings.csv` referenced by the proposal is **not shipped in
this repo**, so unless you supply it yourself, every committed artifact is
synthetic-trained. The model card (`/api/health` → `model`, and the
`meta.pkl` written at training time) records this honestly:

- `source`: `"synthetic"` or `"real"`
- `dataset`: dataset identifier (`synthetic-generator`, or the real CSV name)
- `class_distribution`: `{genuine, fake}` sample counts
- `n_samples`, `n_features`, `trained_at_utc`, `sklearn_version`
- `metrics`: hold-out `accuracy`, per-class `precision`/`recall`/`f1`, and
  macro/weighted F1 (Fake = positive class)
- `honesty_note`: a plain-language caveat about what the metrics mean

**Do not read the synthetic metrics as performance on real postings.** The
synthetic classes are near-separable, so hold-out accuracy/F1 are ~1.0 by
construction; that is an artifact of the generator, not evidence of real-world
skill.

### Real-world evaluation (EMSCAD / `fake_job_postings.csv`)

The full Kaggle dataset is **not shipped in this repo** and is not required to
run the app. Real-data evaluation is opt-in so that the committed model (and
every claim about it) stays honest.

**1. Download / place the dataset**

Download `fake_job_postings.csv` from Kaggle (the "Real / Fake Job Posting
Prediction" / EMSCAD dataset) and place it at:

```
fakejob_app/data/fake_job_postings.csv
```

`data/` is git-ignored, so the multi-MB CSV never gets committed. To use a
different location, pass `--real /path/to/file.csv`, or set the
`REAL_DATASET_PATH` env var. The loader recognises the usual EMSCAD columns
(`title`, `company_profile`, `description`, `requirements`, `benefits`, …) and
builds the model text field from whichever of them are present; the label
column is `fraudulent`. Rows with a missing/invalid label or empty text are
dropped, as are duplicate texts.

**2. Train on real data** (writes `classifier.pkl`, `tfidf.pkl`, `meta.pkl`
with `source="real"`):

```bash
cd fakejob_app
python model_training.py --real data/fake_job_postings.csv
```

**3. Evaluate/report without changing the committed model** (`--eval-only`
loads the current artifacts and scores a held-out split of the real data; it
writes nothing):

```bash
python model_training.py --eval-only --real data/fake_job_postings.csv
```

**4. Compare synthetic vs real training** in throwaway scratch dirs (committed
artifacts untouched):

```bash
python model_training.py --compare --real data/fake_job_postings.csv
```

If the dataset is absent, the command fails clearly with placement instructions
instead of silently pretending real-data evaluation ran.

**What the metrics mean.** Every mode prints and stores a held-out split report:
accuracy, per-class precision/recall/F1 (Fake = positive class), and
macro/weighted F1, plus class distribution and the sklearn version. Real-data
metrics are the meaningful ones; the synthetic numbers are only a pipeline
sanity check (the synthetic classes are near-separable, so they read ~1.0 by
construction).

### Limitations (stated plainly)

- **Dataset bias.** EMSCAD is a fixed 2018-era English-language dataset, skewed
  toward US postings and its own annotation choices. Metrics on it do not
  transfer to other countries, languages, or job boards.
- **English-centric.** TF-IDF is fit on English text and the rule banks are
  primarily English; only a limited set of non-English fee/credential phrases
  is recognized. Predominantly non-Latin-script content raises **H6** (Medium)
  so the result is not a misleading "Low", but the system is not a multilingual
  product — do not rely on it for non-English postings.
- **Not the final authority.** The ML model is one supporting signal. The
  deterministic **Risk Engine** sets every verdict; ML can never override a
  Critical decision. Do not present ML metrics as production fraud-detection
  performance — they are an evaluation of a component, not the system.

### Calibration and provenance in responses

- The ML probability is **calibrated**: `predict_proba` from GBC is
  over-confident, so every analysis shrinks it toward a neutral prior
  (`ML_CALIBRATION_PRIOR=0.5`, `ML_CALIBRATION_SHRINK=0.7`). The displayed
  `ml_probability`/`ml_score` and the `hybrid_score` use the calibrated value;
  the raw model output is still returned as `ml_raw_probability` for
  transparency.
- Every `/api/analyze` response carries a `ml_note` (provenance: training
  source, sample count, validation accuracy) plus a `calibration` metadata
  block, and `/api/health` reports the full model card
  (`source`, `dataset`, `class_distribution`, `estimator`, `n_samples`,
  `n_features`, `validation_accuracy`, `trained_at_utc`, `sklearn_version`,
  `metrics`, `honesty_note`).
- The UI labels the ML card "synthetic-trained · supporting signal" and the
  verdict is always set by the deterministic Risk Engine, never by the ML
  probability.

## Safety notes

- Debug mode is off by default; all settings above are env-controlled.
- Uploads capped at 10 MB with an allowlist (`.pdf/.png/.jpg/.jpeg`).
- Baseline security headers (`nosniff`, `SAMEORIGIN`, strict referrer, CSP).
- This is a screening aid, not a verdict — always verify employers directly.

## Deploy on Render

`fakejob_app/` is the app root; `main` is the deploy branch. For OCR (image /
scanned-PDF upload) you **must** use the Docker runtime — see
[OCR on Render / Docker](#ocr-on-render--docker). The native runtime (no root/apt)
can still run paste-text, text-based PDFs, and the scanner.

> **OCR (image / scanned-PDF upload) requires the Docker runtime.** The native
> Python runtime on Render has no root/apt access, so `tesseract` and
> `poppler-utils` **cannot** be installed there — image/scanned-PDF uploads
> return a clean `400`. To enable OCR, deploy the shipped `render.yaml`
> (Blueprint) or set Language = Docker. Confirm availability any time at
> `GET /api/health` → `{"ocr": {"tesseract": …}}`.

The free-tier web service has an **ephemeral disk**, so the SQLite file resets
on every deploy or restart. For durable scan history, attach a free Postgres:

1. Render Dashboard → **New → PostgreSQL** (free instance).
2. Copy the **Internal Database URL** (the External URL works too for local
   testing).
3. In the web service → **Environment** → add the variables:
   - `DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<dbname>?sslmode=require`
   - `SCAN_API_TOKEN=<long random string>` (required to trigger scans — generate
     one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `RATE_LIMIT_ANALYZE` / `RATE_LIMIT_SCAN` (defaults: `30/minute`, `5/minute`)
4. Save + redeploy. The schema is created on first boot (idempotent), so there
   is no manual migration step.

Without `DATABASE_URL` the app falls back to `SCAM_SENTRY_DB`
(`scam_sentry.db`) as before, which is fine for local development.

> **LLM note:** if you enable `LLM_ENABLED=true`, the app will refuse to boot
> until `SCAN_API_TOKEN` and the rate limits are set — see [Abuse & cost
> control](#abuse--cost-control).

## OCR on Render / Docker

Image and scanned-PDF extraction needs two OS packages that `pip` cannot
provide: `tesseract-ocr` (OCR engine) and `poppler-utils` (`pdftoppm`, PDF →
image). The `Dockerfile` installs both and **fails the build if either is
missing**. Render's native Python runtime has no root/apt, so those packages
exist **only** when the service is built from the Dockerfile. A native deploy
will return `"ocr":{"tesseract":false}` and reject image/scanned-PDF uploads
with a clean `400` (paste-text and text-based PDFs still work).

### Option 1 — Blueprint (recommended): `render.yaml`

The repo ships a `render.yaml` that pins `runtime: docker` and the correct
paths:

```yaml
runtime: docker
dockerfilePath: ./fakejob_app/Dockerfile
dockerContext: ./fakejob_app
healthCheckPath: /api/health
```

1. Render Dashboard → **New → Blueprint** → connect this repo.
2. Render reads `render.yaml` and creates the service as a **Docker** web
   service. Provide values for `SCAN_API_TOKEN` (and `DATABASE_URL` if you have
   Postgres) when prompted (`sync: false` keeps them out of git).
3. **Apply** the Blueprint, then redeploy if needed.

### Option 2 — Create the web service manually

1. Render Dashboard → **New → Web Service** → connect this repo.
2. Set **Language = Docker** (do not pick Python).
   - **Dockerfile Path:** `fakejob_app/Dockerfile`
   - **Docker Context Directory:** `fakejob_app`
3. Environment (nothing OCR-specific — the binaries are baked into the image):
   - `SCAN_API_TOKEN=<long random>` and the rate limits (to trigger scans)
   - `DATABASE_URL=postgresql://…?sslmode=require` (durable history; optional)
   - Optional `SCAN_ALLOW_ANONYMOUS=true` for a token-free demo dashboard
4. **Create / Redeploy.** The build runs `tesseract --version && pdftoppm -v`, so
   a missing OCR layer fails the deploy instead of shipping silently.

### Post-deploy verification

```bash
APP=https://<your-app>.onrender.com

# 1. OCR binaries present? (must be true/true on a Docker deploy)
curl -s $APP/api/health
#    -> {"status":"ok", ..., "ocr":{"tesseract":true,"pdf_render":true}}

# 2. Image / screenshot (needs OCR)
curl -s -X POST $APP/api/analyze/file -F "file=@poster.png"
#    -> 200 with the verdict; 400 only if OCR is genuinely absent

# 3. Text-based PDF (works with or without OCR)
curl -s -X POST $APP/api/analyze/file -F "file=@job.pdf"

# 4. Pasted text (no OCR at all)
curl -s -X POST $APP/api/analyze/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Senior Engineer at Acme Corp, Remote. Build APIs with Python."}'
#    -> 200
```

In the UI: **/analyze** → upload an image (OCR), upload a text PDF (no OCR), or
paste text (no OCR). Startup logs also print a line such as
`OCR toolchain: tesseract=True (cmd='tesseract'), pdf_render=True (poppler)`.

**Troubleshooting:** if `tesseract` is `false` in `/api/health`, the service is
on the **native** runtime (or a stale image). Switch it to Docker (Options 1/2)
and redeploy; you cannot `apt-get install` on the native runtime.

> **Local Docker:** `docker build -t scam-sentry fakejob_app && docker run -p 5000:5000 scam-sentry`
> runs with both binaries installed.

## Project structure

```
fakejob_app/
├── app.py                # Flask app, API, dashboard routes
├── config.py             # All settings (env-overridable)
├── scan.py               # Scanner CLI (cron / daemon)
├── taxonomy.py           # world industry/role classification for the dashboard pickers
├── location.py           # country/region normalization for the dashboard filters
├── cv_utils.py           # CV upload text extraction (PDF/TXT/DOCX)
├── cv_matcher.py         # CV -> scanned-job relevance scoring (not risk)
├── risk/                 # indicators, engine, llm_enhancer, verification, actions
├── scanner/              # base.py + remoteok/remotive/arbeitnow/jobicy
├── services/             # scanner_service, evaluation_service, scheduler
├── models/job.py         # public storage API (selects backend per call)
├── models/storage.py     # SQLiteBackend + PostgresBackend
├── templates/            # index, dashboard, job_detail
├── static/               # style.css, script.js, dashboard.js, cv_matcher.js
├── tests/                # pytest suite (390+ tests)
├── pytest.ini / .coveragerc   # test + coverage config (gate lives here)
├── Dockerfile / .env.example / requirements.txt
└── artifacts/            # trained model artifacts (auto-generated)
```

## Tests

```bash
cd fakejob_app
pip install -r requirements-dev.txt   # runtime deps + pytest/pytest-cov/pyflakes
python -m pytest                      # full suite (uses pytest.ini / tests/)
python -m pyflakes .                  # lint, expected to be clean
```

### Coverage

Coverage is measured on application source only (tests are excluded) and is
gated in CI. The local command is the same one CI runs:

```bash
cd fakejob_app
python -m pytest --cov --cov-report=term-missing
```

The gate (`fail_under = 78`) lives in `.coveragerc`; the current suite sits
around **82%**. The run fails if coverage drops below the gate, so a real
regression fails CI/build instead of passing silently. Use
`--cov-report=html` to write an HTML report to `htmlcov/`.

## Retraining the model

See **ML honesty** above for full context. In short:

```bash
cd fakejob_app
python model_training.py                          # synthetic (default)
python model_training.py --real fake_job_postings.csv   # EMSCAD/Kaggle CSV
```

Training prints a hold-out report (accuracy / precision / recall / F1) and
writes `classifier.pkl`, `tfidf.pkl`, and a `meta.pkl` model card
(`source`, `sklearn_version`, `metrics`, `honesty_note`, …) under `artifacts/`.
The artifacts reload automatically, so no other step is required.
