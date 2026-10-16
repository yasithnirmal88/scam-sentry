"""
config.py
---------
Central configuration for Scam Sentry.

All thresholds, weights, paths, and magic numbers live here.
Override via environment variables where supported.
"""

import os

APP_DIR = os.path.dirname(__file__)


def _load_env_file(path: str) -> bool:
    """Best-effort ``.env`` loader used at import time.

    Loads ``path`` when it exists, without overriding variables already present
    in the real environment (exported vars always win). Returns True if a file
    was loaded, False otherwise. Never raises: when python-dotenv is missing or
    the file is absent/unreadable the app just runs on the process environment.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    if not os.path.exists(path):
        return False
    try:
        return bool(load_dotenv(path, override=False))
    except Exception:
        return False


# Auto-load a local ``.env`` (next to this file) before any settings are read
# below. ``SCAM_SENTRY_NO_DOTENV`` (1/true/yes/on) disables it so tests and
# hardened deployments can force pure environment variables. Real env vars are
# never overridden.
_NO_DOTENV = os.getenv("SCAM_SENTRY_NO_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}
if not _NO_DOTENV:
    _load_env_file(os.path.join(APP_DIR, ".env"))

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# CV-based job matching (read-only relevance aid beside the Risk Engine).
# CVs use a separate, smaller allowlist than the single-job analyzer. Matching
# ranks ALREADY-scanned jobs against a CV; it never changes a risk verdict and
# never sends CV text to any LLM.
# ---------------------------------------------------------------------------
CV_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}
CV_MIN_TEXT_LENGTH = int(os.getenv("CV_MIN_TEXT_LENGTH", "40"))
# Cap how many stored jobs are considered as match candidates (bound the work).
CV_MAX_JOBS = int(os.getenv("CV_MAX_JOBS", "2000"))
# Explainable blend of TF-IDF cosine similarity + skill/tool term overlap.
# Should sum to 1.0.
CV_TFIDF_WEIGHT = float(os.getenv("CV_TFIDF_WEIGHT", "0.6"))
CV_TERM_WEIGHT = float(os.getenv("CV_TERM_WEIGHT", "0.4"))

# ---------------------------------------------------------------------------
# Upload / OCR hardening (DoS & resource-abuse controls). Uploads are
# untrusted: bound how many PDF pages we read, cap the OCR rasterization DPI,
# and cap the pixel budget of any single decoded image. All env-overridable.
# ---------------------------------------------------------------------------
MAX_PDF_PAGES = int(os.getenv("OCR_MAX_PDF_PAGES", "5"))
PDF_OCR_DPI = int(os.getenv("OCR_PDF_DPI", "150"))
MAX_IMAGE_PIXELS = int(os.getenv("OCR_MAX_IMAGE_PIXELS", "20000000"))

# Explicit path to the Tesseract executable. Tesseract is a *system* dependency
# (apt: tesseract-ocr) that pip never installs, so on hosts where it is not on
# PATH (e.g. a native, non-Docker deploys) OCR is unavailable unless this is
# pointed at a binary. Empty means "search PATH, then the common Windows
# install location" (see ocr_utils).
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

MODEL_DIR = os.path.join(APP_DIR, "artifacts")
MIN_TEXT_LENGTH = 15

# Hybrid scoring weights (rule vs ML). Must sum to 1.0.
RULE_WEIGHT = 0.55
ML_WEIGHT = 0.45

# Score floors so a single decisive signal cannot be averaged away.
CRITICAL_SCORE_FLOOR = 70
STRONG_SCORE_FLOOR = 60

# ML honesty (Phase 4): GradientBoosting probabilities are over-confident, and
# the committed model is trained on a synthetic set. Pull the ML probability
# toward a neutral prior so the ML signal never overstates itself; the rule
# engine stays the source of truth. OFF restores the raw model output.
ML_CALIBRATION = os.getenv("ML_CALIBRATION", "true").lower() == "true"
ML_CALIBRATION_PRIOR = float(os.getenv("ML_CALIBRATION_PRIOR", "0.5"))
ML_CALIBRATION_SHRINK = float(os.getenv("ML_CALIBRATION_SHRINK", "0.7"))

# Legacy thresholds (kept for backward-compatible fields).
FAKE_THRESHOLD = 50
HIGH_RISK_THRESHOLD = 65
MEDIUM_RISK_THRESHOLD = 35

# Training defaults.
TFIDF_MAX_FEATURES = 800
TFIDF_NGRAM_RANGE = (1, 2)
GBC_N_ESTIMATORS = 120
GBC_MAX_DEPTH = 3
GBC_LEARNING_RATE = 0.08
SYNTHETIC_SAMPLES_PER_CLASS = 450
# Real-dataset (EMSCAD / fake_job_postings.csv) support. The committed model is
# synthetic-trained; real mode is opt-in. Place the CSV at the default path
# below, or override with the REAL_DATASET_PATH env var / `--real` CLI flag.
REAL_DATASET_PATH = os.getenv(
    "REAL_DATASET_PATH", os.path.join(APP_DIR, "data", "fake_job_postings.csv")
)

# Server settings (12-factor via env).
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# Logging.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Job Risk Scanner (Phase 1).
DATABASE_PATH = os.getenv("SCAM_SENTRY_DB", os.path.join(APP_DIR, "scam_sentry.db"))
# Persistent storage backend. When DATABASE_URL is set (Render / Neon /
# Supabase Postgres), it is used instead of the local SQLite file. Empty =
# SQLite (the local default).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SCANNER_TIMEOUT = int(os.getenv("SCANNER_TIMEOUT", "20"))
SCANNER_DEFAULT_LIMIT = int(os.getenv("SCANNER_LIMIT", "20"))
SCANNER_USER_AGENT = os.getenv("SCANNER_USER_AGENT", "ScamSentry/1.0 (+job-risk-research)")

# Scheduled scanning (Phase 3). Scheduler only starts when SCAN_ENABLED=true,
# so local dev / offline environments are unaffected by default.
SCAN_ENABLED = os.getenv("SCAN_ENABLED", "false").lower() == "true"
SCAN_INTERVAL_HOURS = float(os.getenv("SCAN_INTERVAL_HOURS", "6"))
SCAN_RUN_ON_STARTUP = os.getenv("SCAN_RUN_ON_STARTUP", "true").lower() == "true"
# Comma-separated subset of registered sources; empty = all sources.
SCAN_SOURCES = [s.strip() for s in os.getenv("SCAN_SOURCES", "").split(",") if s.strip()]
SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", str(SCANNER_DEFAULT_LIMIT)))
# HTTP reliability: total attempts = 1 + SCANNER_RETRIES, linear backoff.
SCANNER_RETRIES = int(os.getenv("SCANNER_RETRIES", "2"))
SCANNER_RETRY_BACKOFF = float(os.getenv("SCANNER_RETRY_BACKOFF", "2"))

# ---------------------------------------------------------------------------
# Company-board scanners (Greenhouse / Lever / Ashby). These vendors expose a
# public, no-auth, read-only JSON board per company. There is no global "all
# jobs" endpoint, so each scanner walks a configurable list of public board
# tokens. Override with a comma-separated env var; the defaults below are
# stable public boards used only as sane starting points.
# ---------------------------------------------------------------------------
GREENHOUSE_BOARDS = [s.strip() for s in os.getenv(
    "GREENHOUSE_BOARDS", "stripe,gitlab,coinbase,databricks,vercel,reddit"
).split(",") if s.strip()]
LEVER_BOARDS = [s.strip() for s in os.getenv(
    "LEVER_BOARDS", "dnb,ppgreatplains,leversys").split(",") if s.strip()]
ASHBY_BOARDS = [s.strip() for s in os.getenv(
    "ASHBY_BOARDS", "openai,ramp,notion,linear").split(",") if s.strip()]
# Cap how many boards a single board-scanner fetches per scan (keeps a large
# --limit from fanning out into dozens of requests).
SCANNER_MAX_BOARDS = int(os.getenv("SCANNER_MAX_BOARDS", "6"))

# Working Nomads is a public, no-auth JSON feed that can be slow to respond.
# Keep a per-source floor so the shared default timeout does not cause a
# spurious empty result.
WORKINGNOMADS_TIMEOUT = int(os.getenv("WORKINGNOMADS_TIMEOUT", "45"))

# Freshness bands (days) for Ghost/Stale signals.
FRESHNESS_STALE_DAYS = int(os.getenv("FRESHNESS_STALE_DAYS", "60"))
FRESHNESS_VERY_STALE_DAYS = int(os.getenv("FRESHNESS_VERY_STALE_DAYS", "90"))

# ---------------------------------------------------------------------------
# Abuse & cost control (Phase 3). Always on; tune via env.
# ---------------------------------------------------------------------------
# Shared secret that must be sent as the `X-Scan-Token` header to trigger a
# scan (POST /api/scan). Fail-closed by default: when no token is set the scan
# endpoint rejects every request unless SCAN_ALLOW_ANONYMOUS=true is set
# explicitly (dev/demo only). Production must set a long random value.
SCAN_API_TOKEN = os.getenv("SCAN_API_TOKEN", "").strip()
# Explicit opt-in for open, unauthenticated scans (local dev/demos only). OFF
# by default so a deployment with no token cannot be triggered by anyone. When
# SCAN_API_TOKEN is set this flag is ignored (the token always wins). The LLM
# startup guard still refuses to boot with LLM_ENABLED=true and no token, so
# the spend path can never be left open. Never enable on a public deployment.
SCAN_ALLOW_ANONYMOUS = os.getenv("SCAN_ALLOW_ANONYMOUS", "false").lower() == "true"
# Per-IP allowed request rate on the analysis endpoints and on the scan-trigger
# endpoint. Flask-Limiter parses these (e.g. "30/minute"). The app refuses to
# boot the LLM layer unless both are set.
RATE_LIMIT_ANALYZE = os.getenv("RATE_LIMIT_ANALYZE", "30/minute").strip()
RATE_LIMIT_SCAN = os.getenv("RATE_LIMIT_SCAN", "5/minute").strip()
# Per-IP limit for the public *read* endpoints (jobs list/detail, scan
# status/history, sources, taxonomy, dashboard pages). Deliberately well above
# the write endpoints (analyze/scan) and sized so live scan polling and normal
# dashboard browsing are never throttled; it still blunts bulk scraping.
RATE_LIMIT_READ = os.getenv("RATE_LIMIT_READ", "240/minute").strip()
# CV matching (POST /api/match/cv) does file parsing + scoring over the stored
# jobs, so it is a write-ish endpoint; throttle it like analyze/scan.
RATE_LIMIT_MATCH = os.getenv("RATE_LIMIT_MATCH", "30/minute").strip()
# Reverse-proxy trust for the real client IP. Render (and similar PaaS) place a
# single proxy in front of the app, so request.remote_addr is the proxy, not the
# user, and every request lands in one rate-limit bucket. Trust this many
# X-Forwarded-For hops when resolving the client IP (1 = Render's one proxy).
# Set to 0 when the app is exposed directly (no proxy) so a spoofed
# X-Forwarded-For cannot evade the limiter. Local dev sends no proxy headers and
# needs no change.
TRUSTED_PROXY_HOPS = max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "1")))

# ---------------------------------------------------------------------------
# Optional LLM enhancement layer (OpenAI-compatible chat/completions).
# Disabled by default. The deterministic Risk Engine stays the source of
# truth for the risk level; the LLM only rewrites the human-facing summary
# and adds a short reasoning note. Any failure degrades to engine output.
# ---------------------------------------------------------------------------
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() == "true"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "12"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
# Scanned listings stay zero-token unless this is explicitly enabled.
LLM_SCANNER_ENABLED = os.getenv("LLM_SCANNER_ENABLED", "false").lower() == "true"
