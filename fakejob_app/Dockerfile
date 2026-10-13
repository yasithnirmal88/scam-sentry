# Scam Sentry — production image (gunicorn, no scheduler by default).
# Base pinned to a specific Python minor + Debian release (bookworm) for
# reproducible builds; swap the digest in for full reproducibility if needed.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SCAM_SENTRY_DB=/data/scam_sentry.db

# OCR + PDF system dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Dedicated non-root user. /app holds the code; /data is the writable spot for
# the SQLite DB (mount a volume there to persist it, or set DATABASE_URL).
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app /data \
 && chown -R appuser:appuser /app /data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"]

# Single worker by default (ML model is loaded per worker; raise --workers
# only if you have RAM to spare). Scheduler stays off unless SCAN_ENABLED=true.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "app:app"]
