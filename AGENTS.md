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
- `fakejob_app/models/job.py` — SQLite storage (`jobs`, `scan_history`).
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
- SQLite access goes through `models/job.py::_connect` (a context manager that
  closes the connection — the raw `sqlite3` context manager does not).
- `normalize_url` only accepts http(s); other schemes return "".
- Env-var config lives in `config.py`; keep new settings off by default.

## Deploy

Render free tier (no Docker). `fakejob_app/` is the app root. `main` is the
deploy branch.
