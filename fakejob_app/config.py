"""
config.py
---------
Central configuration for Scam Sentry.

All thresholds, weights, paths, and magic numbers live here.
Override via environment variables where supported.
"""

import os

APP_DIR = os.path.dirname(__file__)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

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

# Freshness bands (days) for Ghost/Stale signals.
FRESHNESS_STALE_DAYS = int(os.getenv("FRESHNESS_STALE_DAYS", "60"))
FRESHNESS_VERY_STALE_DAYS = int(os.getenv("FRESHNESS_VERY_STALE_DAYS", "90"))

# ---------------------------------------------------------------------------
# Abuse & cost control (Phase 3). Always on; tune via env.
# ---------------------------------------------------------------------------
# Shared secret that must be sent as the `X-Scan-Token` header to trigger a
# scan (POST /api/scan). Empty = no-token dev/demo mode: scans run open only
# while the LLM layer is off (`LLM_ENABLED=false`, no spend / no off-box text);
# `_assert_secure_startup` refuses to boot with LLM_ENABLED=true unless a token
# is set. Production must set a long random value.
SCAN_API_TOKEN = os.getenv("SCAN_API_TOKEN", "").strip()
# Per-IP allowed request rate on the analysis endpoints and on the scan-trigger
# endpoint. Flask-Limiter parses these (e.g. "30/minute"). The app refuses to
# boot the LLM layer unless both are set.
RATE_LIMIT_ANALYZE = os.getenv("RATE_LIMIT_ANALYZE", "30/minute").strip()
RATE_LIMIT_SCAN = os.getenv("RATE_LIMIT_SCAN", "5/minute").strip()

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
