# AGENTS.md — Scam Sentry

Repo for the Scam Sentry job-scam risk analyzer. Application code lives in
`fakejob_app/`.

## Layout

- `fakejob_app/risk/` — deterministic Risk Engine (source of truth for the
  verdict). Graded indicators C1–C4 / H1–H5 / M1–M5 / L1–L3, determination
  rules, consistency safety nets, freshness, language discipline.
  `risk/llm_enhancer.py` is an optional, disabled-by-default layer that only
  rewrites wording; it never changes the risk level.
- `fakejob_app/scanner/` — public job-board sources (registry + BaseScanner).
- `fakejob_app/models/` — storage: `job.py` is the public facade (backend
  agnostic); `storage.py` holds the SQLite + Postgres backends.
- `fakejob_app/services/` — scan orchestration + scheduler.
- `fakejob_app/app.py` — Flask app / API.
- `fakejob_app/artifacts/` — committed pickled ML model (classifier/tfidf/meta).

## Commands (run from `fakejob_app/`)

```bash
pip install -r requirements-dev.txt   # includes runtime deps
python -m pytest tests -q             # full suite (~8s, 144 tests)
python -m pyflakes .                  # keep clean
python model_training.py              # retrain artifacts (fix version warning)
python scan.py --list-sources         # CLI scanner
```

## Conventions

- The Risk Engine is authoritative; the LLM layer is optional and must degrade
  to engine output on any failure.
- Language discipline: never emit "this is a scam/fake" — `risk/language.py`
  enforces this and LLM output is filtered through it.
- Storage goes through `models/job.py` (public API), which picks a backend in
  `models/storage.py`: an explicit `db_path` wins, then `DATABASE_URL`
  (Postgres), then the local SQLite file. Never open a raw connection for app
  reads/writes.
- API abuse control: `POST /api/scan` is fail-closed — it requires an
  `X-Scan-Token` header equal to `SCAN_API_TOKEN`, and with no token set it
  rejects every request unless `SCAN_ALLOW_ANONYMOUS=true` (dev/demo only;
  ignored when a token is set). The analysis and scan endpoints are
  rate-limited per IP; with `LLM_ENABLED=true` the app refuses to start unless
  the token and rate limits are configured.
- OCR (`ocr_utils.py`) needs the **system** binaries Tesseract (`tesseract-ocr`)
  and Poppler (`poppler-utils`) — pip cannot install them, so they live in the
  Dockerfile (verified at build time). Set `TESSERACT_CMD` for a non-PATH
  install; when the engine is absent, image/scanned-PDF uploads return a clean
  400 and text paste / text-based PDFs keep working. Text-layer PDFs never touch
  Tesseract.
- `normalize_url` only accepts http(s); other schemes return "".
- Env-var config lives in `config.py`; keep new settings off by default.
  `config.py` auto-loads a local `.env` (python-dotenv, non-overriding) unless
  `SCAM_SENTRY_NO_DOTENV` is truthy; tests set that flag via `tests/conftest.py`
  so the suite is isolated from a developer's `.env`.

## Deploy

Render free tier (no Docker). `fakejob_app/` is the app root. `main` is the
deploy branch.
