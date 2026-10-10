# Scam Sentry — production image (gunicorn, no scheduler by default).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OCR + PDF system dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

# Single worker by default (ML model is loaded per worker; raise --workers
# only if you have RAM to spare). Scheduler stays off unless SCAN_ENABLED=true.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "app:app"]
