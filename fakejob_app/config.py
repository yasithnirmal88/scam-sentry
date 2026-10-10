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

MODEL_DIR = os.path.join(APP_DIR, "model")
MIN_TEXT_LENGTH = 15

# Hybrid scoring weights (rule vs ML). Must sum to 1.0.
RULE_WEIGHT = 0.55
ML_WEIGHT = 0.45

# Score floors so a single decisive signal cannot be averaged away.
CRITICAL_SCORE_FLOOR = 70
STRONG_SCORE_FLOOR = 60

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
