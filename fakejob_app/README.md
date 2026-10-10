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
  mismatch, ghost/stale), **M1–M5** (medium, incl. aging listings),
  **L1–L3** (low/weak).
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
- No LinkedIn scraping (and no authenticated or paywalled sources).
- No browser automation — liveness is inferred from posting dates and
  wording, not live page checks.
- No accounts, no email alerts, no auto-applying — it never acts on your behalf.

## How it works

- **Risk Engine** (`risk/`): severity-graded indicators (C1–C4 critical,
  H1–H5 high, M1–M4 medium, L1–L3 low) → first-match-wins determination
  rules → confidence, categories, summary, recommended actions, and a
  lightweight employer check. A Critical indicator always forces Critical,
  regardless of the ML score.
- **Hybrid scoring**: transparent rule score blended with a
  `GradientBoostingClassifier` (TF-IDF + engineered fraud features) as a
  supporting signal — never a black box.
- **Scanners** (`scanner/`): RemoteOK, Remotive, Arbeitnow, Jobicy (all free
  public JSON APIs, no auth). Modular `BaseScanner` + registry — adding a
  source is one subclass.
- **Storage** (`models/job.py`): SQLite; jobs upserted by normalized URL,
  every scan recorded in `scan_history` with success/partial/failed status.
- **Scheduler** (`services/scheduler.py`): dependency-free background thread,
  every N hours; manual scans also run async so the web app never blocks.

## Features

- Paste-text / file-upload (PDF, PNG, JPG) analysis with OCR
- Risk dashboard (`/dashboard`): grouped by risk level, counts, filters
  (risk / source / keyword search), job detail pages with full evidence
- One-click scans from the UI, background scheduler, `scan.py` CLI
- 120+ automated tests (`pytest`)

## Running it locally

### 1. System dependencies (OCR only; skip if you only use paste-text + scanner)

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr poppler-utils
# macOS
brew install tesseract poppler
```

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
synthetic data) and is saved to `model/`. With `SCAN_ENABLED=false`
(default) no network scanning happens until you trigger one.

### Production (gunicorn)

```bash
gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 120 app:app
```

Or with Docker:

```bash
cd fakejob_app
docker build -t scam-sentry .
docker run -p 5000:5000 -e SCAN_ENABLED=true scam-sentry
```

## Running a scan

- **UI**: open `/dashboard`, pick sources, click **Run New Scan**
  (progress + auto-refresh; safe to leave the page).
- **API**: `POST /api/scan` → `202` (async); poll `GET /api/scan/status`.
  Add `?sync=1` to wait for completion.
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

| Source | Type | Auth |
|---|---|---|
| RemoteOK | Public JSON API | none |
| Remotive | Public JSON API | none |
| Arbeitnow | Public JSON API | none |
| Jobicy | Public JSON API | none |

No LinkedIn scraping, by design.

## API overview

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analyze/text` | POST `{"text": "..."}` | Single-job risk report |
| `/api/analyze/file` | POST multipart `file` | Single-job risk report (OCR) |
| `/api/jobs?risk_level=&source=&q=&limit=&offset=` | GET | Scanned jobs + totals + per-level counts |
| `/api/jobs/<id>` | GET | One stored job with full risk report |
| `/api/scan` | POST `{"sources": [...], "limit": N}` | Async scan → `202`; `?sync=1` to wait |
| `/api/scan/status` | GET | Running/idle + last recorded run |
| `/api/sources` | GET | Registered scanner names |
| `/api/health` | GET | `{"status": "ok", "model_loaded": true}` |

## Environment variables

See `.env.example`. Highlights:

| Variable | Default | Meaning |
|---|---|---|
| `FLASK_HOST` / `FLASK_PORT` | `0.0.0.0` / `5000` | Server bind |
| `FLASK_DEBUG` | `false` | Never enable in production |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SCAM_SENTRY_DB` | `scam_sentry.db` | SQLite file |
| `SCAN_ENABLED` | `false` | Background scheduler on/off |
| `SCAN_INTERVAL_HOURS` | `6` | Scheduler interval |
| `SCAN_RUN_ON_STARTUP` | `true` | First scan shortly after boot |
| `SCAN_SOURCES` | *(all)* | Comma-separated source subset |
| `SCAN_LIMIT` | `20` | Jobs per source (1–100) |
| `SCANNER_TIMEOUT` / `SCANNER_RETRIES` / `SCANNER_RETRY_BACKOFF` | `20` / `2` / `2` | HTTP reliability |

## Safety notes

- Debug mode is off by default; all settings above are env-controlled.
- Uploads capped at 10 MB with an allowlist (`.pdf/.png/.jpg/.jpeg`).
- Baseline security headers (`nosniff`, `SAMEORIGIN`, strict referrer).
- This is a screening aid, not a verdict — always verify employers directly.

## Project structure

```
fakejob_app/
├── app.py                # Flask app, API, dashboard routes
├── config.py             # All settings (env-overridable)
├── scan.py               # Scanner CLI (cron / daemon)
├── risk/                 # indicators.py, engine.py, verification.py, actions.py
├── scanner/              # base.py + remoteok/remotive/arbeitnow/jobicy
├── services/             # scanner_service, evaluation_service, scheduler
├── models/job.py         # SQLite jobs + scan_history
├── templates/            # index, dashboard, job_detail
├── static/               # style.css, script.js, dashboard.js
├── tests/                # pytest suite (51+ tests)
├── Dockerfile / .env.example / requirements.txt
└── model/                # trained artifacts (auto-generated)
```

## Tests

```bash
cd fakejob_app
pip install -r requirements-dev.txt
python -m pytest tests -q
```
