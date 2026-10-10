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
  H1–H5 high, M1–M5 medium, L1–L3 low) → first-match-wins determination
  rules → confidence, categories, summary, recommended actions, and a
  lightweight employer check. A Critical indicator always forces Critical,
  regardless of the ML score.
- **Hybrid scoring**: transparent rule score blended with a
  `GradientBoostingClassifier` (TF-IDF + engineered fraud features) as a
  supporting signal — never a black box.
- **Scanners** (`scanner/`): RemoteOK, Remotive, Arbeitnow, Jobicy (all free
  public JSON APIs, no auth). Modular `BaseScanner` + registry — adding a
  source is one subclass.
- **Storage** (`models/job.py` + `models/storage.py`): SQLite by default;
  when `DATABASE_URL` is set, the same public API runs on Postgres (Render /
  Neon / Supabase free tier). Jobs upsert by normalized URL and every scan is
  recorded in `scan_history`. **Deploy note:** on Render's free tier the disk
  is ephemeral — the local SQLite file (and all scan history) is wiped on
  every deploy or restart. Set `DATABASE_URL` for durable storage.
- **Scheduler** (`services/scheduler.py`): dependency-free background thread,
  every N hours; manual scans also run async so the web app never blocks.

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
- One-click scans from the UI, background scheduler, `scan.py` CLI
- Optional LLM enhancement layer (OpenAI-compatible; off by default)
- 140+ automated tests (`pytest`)

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
synthetic data) and is saved to `artifacts/`. With `SCAN_ENABLED=false`
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
| `/api/health` | GET | `{"status": "ok", "model_loaded": false}` — `model_loaded` flips to `true` after the first `/api/analyze` (the ML model loads lazily) |

## Environment variables

See `.env.example`. Highlights:

| Variable | Default | Meaning |
|---|---|---|
| `FLASK_HOST` / `FLASK_PORT` | `0.0.0.0` / `5000` | Server bind |
| `FLASK_DEBUG` | `false` | Never enable in production |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SCAM_SENTRY_DB` | `scam_sentry.db` | SQLite file |
| `DATABASE_URL` | *(empty)* | Postgres connection string. When set, it takes precedence over the SQLite file (Render/Neon/Supabase). Leave empty for local SQLite |
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

## Safety notes

- Debug mode is off by default; all settings above are env-controlled.
- Uploads capped at 10 MB with an allowlist (`.pdf/.png/.jpg/.jpeg`).
- Baseline security headers (`nosniff`, `SAMEORIGIN`, strict referrer).
- This is a screening aid, not a verdict — always verify employers directly.

## Deploy on Render (free tier, no Docker)

`fakejob_app/` is the app root; `main` is the deploy branch.

The free-tier web service has an **ephemeral disk**, so the SQLite file resets
on every deploy or restart. For durable scan history, attach a free Postgres:

1. Render Dashboard → **New → PostgreSQL** (free instance).
2. Copy the **Internal Database URL** (the External URL works too for local
   testing).
3. In the web service → **Environment** → add the variable:
   `DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<dbname>?sslmode=require`
4. Save + redeploy. The schema is created on first boot (idempotent), so there
   is no manual migration step.

Without `DATABASE_URL` the app falls back to `SCAM_SENTRY_DB`
(`scam_sentry.db`) as before, which is fine for local development.

## Project structure

```
fakejob_app/
├── app.py                # Flask app, API, dashboard routes
├── config.py             # All settings (env-overridable)
├── scan.py               # Scanner CLI (cron / daemon)
├── risk/                 # indicators, engine, llm_enhancer, verification, actions
├── scanner/              # base.py + remoteok/remotive/arbeitnow/jobicy
├── services/             # scanner_service, evaluation_service, scheduler
├── models/job.py         # public storage API (selects backend per call)
├── models/storage.py     # SQLiteBackend + PostgresBackend
├── templates/            # index, dashboard, job_detail
├── static/               # style.css, script.js, dashboard.js
├── tests/                # pytest suite (140+ tests)
├── Dockerfile / .env.example / requirements.txt
└── artifacts/            # trained model artifacts (auto-generated)
```

## Tests

```bash
cd fakejob_app
pip install -r requirements-dev.txt
python -m pytest tests -q
```
