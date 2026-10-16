"""
app.py
------
Flask backend for the Intelligent Fake Job Advertisement Detection System.

Pipeline (matches the project proposal's workflow diagram):

  User Input (paste text / upload PDF / upload image)
        |
        v
  OCR (if PDF/image)              [ocr_utils.py]
        |
        v
  Text Preprocessing (NLP)        [text_processing.py]
        |
        v
  TF-IDF Feature Extraction   +   Rule-based Fraud Features
        |                              |          [fraud_features.py]
        +---------------+--------------+
                         v
              Hybrid ML Classifier      [model_training.py]
                         |
                         v
        Fake / Genuine Prediction + Confidence Score
                         |
                         v
        Explanation Engine (evidence-based, not raw SHAP words)

Verdict ownership (do not conflate the two systems):
  * Authoritative risk decision -> risk/indicators.py + risk/engine.py.
    `classify()` reports the engine's verdict in `overall_risk_level`,
    `risk_categories`, `key_indicators`, and `recommended_actions`.
  * fraud_features.py + the hybrid ML score are a SUPPORTING signal only
    (reported as `hybrid_score` / `prediction` / `risk_level` for backward
    compatibility). They must never override or contradict the engine.
"""

import logging
import os
import pickle
import threading

import numpy as np
from flask import Flask, request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from scipy.sparse import hstack, csr_matrix
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import fraud_features
from fraud_features import extract_all_features, FEATURE_KEYS
from text_processing import preprocess
import ocr_utils
from ocr_utils import extract_text
from model_training import build_synthetic_dataset, load_model_metadata, train
from risk.indicators import analyze_indicators
from risk.engine import assess_risk, has_critical
from risk.verification import verify_employer
from risk.actions import generate_actions
from models.job import count_jobs, get_job, init_db, list_jobs, risk_counts
from scanner import list_sources

APP_DIR = config.APP_DIR
ALLOWED_EXTENSIONS = config.ALLOWED_EXTENSIONS
MAX_CONTENT_LENGTH = config.MAX_CONTENT_LENGTH
MODEL_DIR = config.MODEL_DIR

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                    format=config.LOG_FORMAT)
logger = logging.getLogger("scam_sentry")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def apply_proxy_fix(flask_app, hops=None):
    """Resolve the real client IP when running behind a trusted reverse proxy.

    Render (and similar PaaS) put a single proxy in front of the app, so
    ``request.remote_addr`` is the proxy's address and per-IP rate limits would
    lump every visitor into one bucket. Wrapping the WSGI app in ``ProxyFix``
    makes ``REMOTE_ADDR`` (and therefore Flask-Limiter's ``get_remote_address``)
    the real client IP taken from the right-most trusted ``X-Forwarded-For`` hop.

    Only the client IP is derived from proxy headers (``x_for``); proto/host/
    port/prefix are left untouched. ``hops<=0`` disables the fix so a
    directly-exposed app cannot be tricked by a spoofed ``X-Forwarded-For``.
    Local development sends no proxy headers, so the peer address is used
    unchanged either way.
    """
    hops = config.TRUSTED_PROXY_HOPS if hops is None else hops
    if hops and hops > 0:
        flask_app.wsgi_app = ProxyFix(
            flask_app.wsgi_app, x_for=hops,
            x_proto=0, x_host=0, x_port=0, x_prefix=0)
    return flask_app


apply_proxy_fix(app)

# Per-IP rate limits (abuse & cost control). Limits are callables so they can
# be tuned via env/config without restarting; tests toggle `limiter.enabled`.
# In-memory storage is fine for a single Render worker; per-worker counters
# on gunicorn multi-worker would need a shared storage backend.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _assert_secure_startup():
    """Refuse to boot the LLM layer on an un-hardened config.

    The LLM layer is the only path that spends money and sends user text
    off-box, so enabling it without an API token and rate limits is a fatal
    config error, not a warning.
    """
    if not config.LLM_ENABLED:
        return
    missing = []
    if not config.SCAN_API_TOKEN:
        missing.append("SCAN_API_TOKEN is not set")
    if not (config.RATE_LIMIT_ANALYZE and config.RATE_LIMIT_SCAN):
        missing.append("rate limits are not configured "
                       "(RATE_LIMIT_ANALYZE / RATE_LIMIT_SCAN)")
    if missing:
        raise SystemExit(
            "Refusing to start: LLM_ENABLED=true but " + "; ".join(missing)
            + ". Set them before enabling the LLM layer."
        )


_assert_secure_startup()


@app.after_request
def _security_headers(response):
    """Baseline hardening headers (clickjacking, MIME sniffing, same-origin
    content policy). Templates load static JS/CSS same-origin plus Google
    Fonts; inline style attributes are used, so style-src allows them."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    )
    # Never let the browser serve a stale copy of our JS/CSS after a deploy
    # (no cache-busting URLs on the pages). No-store keeps demo iterations
    # visible immediately.
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(413)
def _file_too_large(_exc):
    return jsonify({"error": "File is too large. Please upload a file under 10 MB."}), 413


@app.errorhandler(429)
def _rate_limited(_exc):
    return jsonify({"error": "Too many requests. Please slow down and try again."}), 429

_clf = None
_tfidf = None
_model_lock = threading.Lock()


def load_or_train_model():
    """Load saved model artifacts, training them on first run if missing."""
    global _clf, _tfidf
    clf_path = os.path.join(MODEL_DIR, "classifier.pkl")
    tfidf_path = os.path.join(MODEL_DIR, "tfidf.pkl")

    if not (os.path.exists(clf_path) and os.path.exists(tfidf_path)):
        logger.info("No trained model found - training on a fresh synthetic dataset "
                    "(first run only, takes a few seconds)...")
        df = build_synthetic_dataset(n_per_class=config.SYNTHETIC_SAMPLES_PER_CLASS)
        train(df)

    with open(clf_path, "rb") as f:
        _clf = pickle.load(f)
    with open(tfidf_path, "rb") as f:
        _tfidf = pickle.load(f)
    logger.info("Model loaded.")


def _ensure_model():
    """Load the ML model on first use (thread-safe, one-time).

    Keeping import cheap matters on Render's free tier: the scanner and
    dashboard never touch the ML model, so deferring the load speeds up
    boot and avoids the ML memory cost unless a single-job analysis runs.
    """
    if _clf is not None and _tfidf is not None:
        return
    with _model_lock:
        if _clf is None or _tfidf is None:
            load_or_train_model()


def vectorize(text):
    cleaned = preprocess(text)
    tfidf_vec = _tfidf.transform([cleaned])
    result = extract_all_features(text)
    rule_vec = csr_matrix(
        np.array([[result["features"].get(k, 0) for k in FEATURE_KEYS]], dtype=float)
    )
    combined = hstack([tfidf_vec, rule_vec]).tocsr()
    return combined, result


def _ml_note():
    """One honest sentence about where the ML probability comes from."""
    meta = load_model_metadata()
    if not meta.get("available"):
        return ("The ML probability is a supporting signal only; the verdict "
                "is set by the deterministic Risk Engine.")
    source = "synthetic training data"
    if meta.get("source") == "real":
        source = "a real dataset"
    acc = meta.get("validation_accuracy")
    acc_str = f"{acc * 100:.1f}%" if acc is not None else "n/a"
    estimator = meta.get("estimator") or "GradientBoosting"
    return (
        f"ML probability comes from a {estimator} model trained on {source} "
        f"(n_samples={meta.get('n_samples', '?')}, validation accuracy "
        f"{acc_str}); the verdict is set by the deterministic Risk Engine and "
        f"the ML output is a supporting signal only."
    )


def classify(text, posted_at=None, use_llm=None):
    """Full risk report for one posting.

    `posted_at` is optional (ISO string, epoch, or datetime) and feeds the
    Ghost/Stale freshness signals. Single-job paste/upload calls omit it,
    which is handled gracefully as "unknown date".

    `use_llm` controls the optional LLM enhancement layer. When None it
    defaults to `config.LLM_ENABLED`. The LLM never changes the risk level
    decided by the Risk Engine; it only improves the summary/wording.
    """
    if not text or len(text.strip()) < config.MIN_TEXT_LENGTH:
        return {
            "error": "Not enough text was found to analyse. Please paste a "
                      "longer job advertisement or upload a clearer file."
        }

    _ensure_model()
    X, rule_result = vectorize(text)
    # ML honesty (Phase 4): GradientBoosting predict_proba is over-confident,
    # and this model is trained on a synthetic set. Shrink the raw probability
    # toward a neutral prior so the ML signal never overstates itself, and
    # expose the raw value + provenance for transparency. The rule engine sets
    # the verdict regardless.
    raw_ml_100 = float(_clf.predict_proba(X)[0][1]) * 100  # 0-100, raw
    cal_prior = config.ML_CALIBRATION_PRIOR * 100
    ml_proba_fake = raw_ml_100
    if config.ML_CALIBRATION:
        ml_proba_fake = cal_prior + (raw_ml_100 - cal_prior) * config.ML_CALIBRATION_SHRINK

    rule_score = rule_result["rule_score"]  # 0-100, transparent

    # Hybrid final score: weight the transparent rule-based evidence
    # slightly higher than the ML model, since the ML model is trained on
    # a limited dataset while the rule engine encodes well-established
    # fraud indicators directly.
    final_score = round(config.RULE_WEIGHT * rule_score + config.ML_WEIGHT * ml_proba_fake, 1)

    # A request for payment or for sensitive personal information (bank
    # details, national ID, passport number, etc.) is, on its own, a
    # decisive real-world scam signal - the kind of evidence a human
    # reviewer would flag immediately regardless of how "professional"
    # the rest of the posting reads. A weighted-average score can let the
    # ML side dilute a single such red flag below the Fake threshold, so
    # apply a floor whenever one fires rather than let it get averaged away.
    # The floor keys off BOTH the legacy fraud-feature flags and the new
    # graded indicators so score and verdict logic stay aligned.
    # posted_at (scanned listings only) feeds the freshness signals here
    # and in the verdict below via the single shared analysis pass.
    fresh_meta = {"posted_at": posted_at} if posted_at else None
    fired_early = analyze_indicators(text, fresh_meta)
    if rule_result.get("critical_hit") or has_critical(fired_early):
        final_score = max(final_score, fraud_features.CRITICAL_SCORE_FLOOR)
    elif rule_result.get("strong_hit"):
        final_score = max(final_score, fraud_features.STRONG_SCORE_FLOOR)

    prediction = "Fake" if final_score >= config.FAKE_THRESHOLD else "Genuine"
    confidence = final_score if prediction == "Fake" else round(100 - final_score, 1)

    # `risk_level` above is the HYBRID score band (legacy + ML) and is kept
    # for backward compatibility only. It is a supporting signal: the
    # authoritative verdict is `overall_risk_level`, computed by the Risk
    # Engine further below.
    if final_score >= config.HIGH_RISK_THRESHOLD:
        risk_level = "HIGH"
    elif final_score >= config.MEDIUM_RISK_THRESHOLD:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Backward-compatible legacy indicator list (fraud_features). The
    # authoritative, structured indicator list is `key_indicators` from the
    # Risk Engine below; this one is retained so older clients keep working.
    indicators = [
        {
            "label": d["label"],
            "detail": d["detail"],
            "severity": d["severity"],
        }
        for d in rule_result["indicators"]
    ]

    if not indicators:
        indicators_message = ("No common fraud indicators were detected. The "
                               "advertisement's structure and content are "
                               "consistent with genuine job postings.")
    else:
        indicators_message = None

    # ---- Risk Engine verdict (AUTHORITATIVE, source of truth) -------------
    # The deterministic Risk Engine (risk/indicators.py + risk/engine.py)
    # alone decides `overall_risk_level`, `risk_categories`, `key_indicators`,
    # and `recommended_actions`. The hybrid ML score above is a supporting
    # signal only and never overrides this: any Critical indicator forces a
    # Critical level inside assess_risk's determination rules regardless of
    # the ML/hybrid score.
    # (fired_early was already computed above for the hybrid floor; reuse it.)
    fired = fired_early
    assessment = assess_risk(fired)
    verification = verify_employer(text, fired)
    actions = generate_actions(fired, assessment["overall_risk_level"])

    # ---- Optional LLM enhancement (never changes the verdict) -------------
    # The deterministic Risk Engine above is the SOURCE OF TRUTH for the
    # risk level. When enabled, the LLM only rewrites the human-facing
    # summary and adds a short reasoning note. Any failure, timeout, or
    # unsafe output degrades silently to the engine's own summary.
    engine_summary = assessment["summary"]
    want_llm = config.LLM_ENABLED if use_llm is None else bool(use_llm)
    llm_summary = llm_explanation = llm_model = None
    if want_llm:
        try:
            from risk.llm_enhancer import enhance as _llm_enhance
            enhanced = _llm_enhance({
                "overall_risk_level": assessment["overall_risk_level"],
                "risk_categories": assessment["risk_categories"],
                "confidence": assessment["confidence"],
                "summary": engine_summary,
                "key_indicators": assessment["key_indicators"],
            }, text)
            if enhanced:
                llm_summary = enhanced.get("summary")
                llm_explanation = enhanced.get("explanation")
                llm_model = enhanced.get("model")
        except Exception as exc:  # never let the enhancer break analysis
            logger.warning("LLM enhancement skipped: %s", exc)
    final_summary = llm_summary or engine_summary

    hybrid_01 = round(final_score / 100.0, 3)
    rule_01 = round(rule_score / 100.0, 3)
    ml_01 = round(ml_proba_fake / 100.0, 3)

    return {
        # New structured response (primary).
        "overall_risk_level": assessment["overall_risk_level"],
        "risk_categories": assessment["risk_categories"],
        "confidence": assessment["confidence"],
        "summary": final_summary,
        "key_indicators": assessment["key_indicators"],
        "employer_verification": verification,
        "recommended_actions": actions,
        # LLM enhancement metadata (the verdict above is unchanged by it).
        "llm_enhanced": bool(llm_summary),
        "llm_model": llm_model,
        "llm_explanation": llm_explanation,
        "engine_summary": engine_summary,
        "hybrid_score": hybrid_01,
        "rule_score": rule_01,
        "ml_score": ml_01,
        "ml_raw_probability": round(raw_ml_100, 1),
        "ml_note": _ml_note(),
        "calibration": {
            "applied": bool(config.ML_CALIBRATION),
            "prior": config.ML_CALIBRATION_PRIOR,
            "shrink": config.ML_CALIBRATION_SHRINK,
        },
        "raw_text_preview": text[:800],
        # Backward-compatible fields.
        "prediction": prediction,
        "confidence_score": confidence,
        "fake_probability": final_score,
        "risk_level": risk_level,
        "ml_probability": round(ml_proba_fake, 1),
        "rule_score_100": rule_score,
        "indicators": indicators,
        "indicators_message": indicators_message,
        "company_detected": rule_result["company_detected"],
        "extracted_text_preview": text[:800],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze/text", methods=["POST"])
@limiter.limit(lambda: config.RATE_LIMIT_ANALYZE)
def analyze_text():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    result = classify(text)
    if "error" in result:
        return jsonify(result), 400
    result["source"] = "pasted-text"
    return jsonify(result)


@app.route("/api/analyze/file", methods=["POST"])
@limiter.limit(lambda: config.RATE_LIMIT_ANALYZE)
def analyze_file():
    if "file" not in request.files:
        return jsonify({"error": "No file was uploaded."}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file was selected."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Unsupported file type. Please upload a PDF, "
                                  "JPG, JPEG, or PNG file."}), 400

    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"error": "The uploaded file is empty."}), 400
    try:
        extracted_text, method = extract_text(file.filename, file_bytes)
    except ValueError as exc:
        # Expected, user-facing failures (bad type, corrupt file, over the
        # OCR page/pixel limits) carry a clean message.
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("File extraction failed")
        return jsonify({"error": "Could not read the uploaded file. Please "
                                  "try a different PDF or image."}), 400

    result = classify(extracted_text)
    if "error" in result:
        return jsonify(result), 400
    result["source"] = f"file-upload ({method})"
    return jsonify(result)


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": _clf is not None,
        "model": _health_model_info(),
        # Diagnostic only: image/scanned-PDF extraction needs the Tesseract and
        # Poppler system binaries, which pip does not provide. Lets a deployer
        # confirm OCR availability without uploading a file.
        "ocr": {
            "tesseract": ocr_utils.tesseract_available(),
            "pdf_render": ocr_utils.PDF2IMAGE_AVAILABLE,
        },
    })


def _health_model_info():
    """Model provenance for /api/health (never raises)."""
    meta = load_model_metadata()
    return {
        "available": meta.get("available", False),
        "source": meta.get("source"),
        "dataset": meta.get("dataset"),
        "class_distribution": meta.get("class_distribution"),
        "estimator": meta.get("estimator"),
        "n_samples": meta.get("n_samples"),
        "n_features": meta.get("n_features"),
        "validation_accuracy": meta.get("validation_accuracy"),
        "trained_at_utc": meta.get("trained_at_utc"),
        "sklearn_version": meta.get("sklearn_version"),
        "metrics": meta.get("metrics"),
        "honesty_note": meta.get("honesty_note"),
    }

# ---------------------------------------------------------------------------
# Job Risk Scanner API (Phase 1)
# ---------------------------------------------------------------------------

@app.route("/api/jobs", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_list_jobs():
    """List scanned jobs. Query params: risk_level, source, industry, role,
    q, limit, offset."""
    try:
        filters = {
            "risk_level": request.args.get("risk_level"),
            "source": request.args.get("source"),
            "industry": request.args.get("industry"),
            "role": request.args.get("role"),
            "query": request.args.get("q"),
        }
        jobs = list_jobs(
            limit=request.args.get("limit", 50),
            offset=request.args.get("offset", 0),
            **filters,
        )
        return jsonify({
            "jobs": jobs,
            # ``total`` is the number of jobs matching the current filters;
            # ``global_total`` is the unfiltered count across all sources.
            "total": count_jobs(**filters),
            "global_total": count_jobs(),
            "counts": risk_counts(),
        })
    except Exception:
        # Log the full detail server-side; never echo internals (paths/SQL)
        # back to the client.
        logger.exception("Failed to list jobs")
        return jsonify({"error": "Could not list jobs."}), 500


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_get_job(job_id):
    """Full details of one job, including its stored risk report."""
    try:
        job = get_job(job_id)
    except Exception:
        logger.exception("Failed to fetch job %s", job_id)
        return jsonify({"error": "Could not fetch job."}), 500
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


def _scan_request_authorized():
    """The scan trigger is fail-closed by default.

    With ``SCAN_API_TOKEN`` set, the request must carry the matching
    ``X-Scan-Token`` header. When no token is configured the endpoint rejects
    every request unless ``SCAN_ALLOW_ANONYMOUS=true`` is explicitly set
    (local dev/demos only). The LLM startup guard additionally refuses to boot
    with ``LLM_ENABLED=true`` without a token, so the spend path is never left
    open by accident.
    """
    token = config.SCAN_API_TOKEN
    if token:
        return request.headers.get("X-Scan-Token", "") == token
    return bool(getattr(config, "SCAN_ALLOW_ANONYMOUS", False))


@app.route("/api/scan", methods=["POST"])
@limiter.limit(lambda: config.RATE_LIMIT_SCAN)
def api_trigger_scan():
    """Trigger a scan manually. Body (JSON, optional): {sources: [...], limit: N}.

    Requires the `X-Scan-Token` header to match `SCAN_API_TOKEN` (401
    otherwise). With no token configured the endpoint is fail-closed (401)
    unless `SCAN_ALLOW_ANONYMOUS=true` is set explicitly for local demos.
    Sends 429 when the per-IP rate limit is exceeded.

    Runs in a background thread (202) so the web app never blocks.
    Pass ?sync=1 (or {"sync": true}) to wait for completion instead.
    """
    if not _scan_request_authorized():
        if config.SCAN_API_TOKEN:
            error = "Scan authentication is enabled: send a valid X-Scan-Token header."
            hint = ("This server sets SCAN_API_TOKEN, so the dashboard's token-free "
                    "trigger is rejected. Call POST /api/scan with the X-Scan-Token "
                    "header, or (local/demo only) unset SCAN_API_TOKEN and set "
                    "SCAN_ALLOW_ANONYMOUS=true.")
        else:
            error = "Scan authentication is enabled: the scan trigger is fail-closed."
            hint = ("Set SCAN_ALLOW_ANONYMOUS=true in .env for local/demo scans, or "
                    "configure SCAN_API_TOKEN and call POST /api/scan with the "
                    "X-Scan-Token header for programmatic access.")
        return jsonify({"error": error, "hint": hint}), 401

    from services import scheduler
    from services.scanner_service import run_scan

    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or list_sources()
    limit = data.get("limit", config.SCANNER_DEFAULT_LIMIT)
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid 'limit' (1-100)."}), 400
    unknown = [s for s in sources if s not in list_sources()]
    if unknown:
        return jsonify({"error": f"Unknown sources: {unknown}. Available: {list_sources()}"}), 400

    sync = request.args.get("sync") == "1" or data.get("sync") is True
    if sync:
        try:
            summary = run_scan(sources=sources, limit_per_source=limit)
        except Exception:
            logger.exception("Scan failed")
            return jsonify({"error": "Scan failed. Please try again later."}), 500
        summary["counts"] = risk_counts()
        return jsonify(summary)

    result = scheduler.trigger_async(sources=sources, limit=limit)
    if not result.get("accepted"):
        return jsonify(result), 409
    return jsonify(result), 202


@app.route("/api/scan/status", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_scan_status():
    """Current scan state (running/idle) + last recorded run."""
    from services import scheduler
    try:
        return jsonify(scheduler.get_status())
    except Exception:
        logger.exception("Failed to get scan status")
        return jsonify({"error": "Could not get scan status."}), 500


@app.route("/api/scan/history", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_scan_history():
    """Recent scan runs, newest first. Public (dashboard rendering only)."""
    from models.job import list_scan_history
    try:
        runs = list_scan_history(limit=request.args.get("limit", 20))
    except Exception:
        logger.exception("Failed to list scan history")
        return jsonify({"error": "Could not list scan history."}), 500
    return jsonify({"runs": runs})


@app.route("/api/sources", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_list_sources():
    return jsonify({"sources": list_sources()})


@app.route("/api/taxonomy", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def api_taxonomy():
    """World industry categories + the job roles under each, for the
    dashboard's "browse by industry, then role" pickers. Public."""
    from taxonomy import INDUSTRIES
    return jsonify({"industries": INDUSTRIES})


# ---------------------------------------------------------------------------
# Job Risk Dashboard (Phase 2, server-rendered pages on top of the API)
# ---------------------------------------------------------------------------

@app.route("/dashboard", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def dashboard():
    """Dashboard home: jobs grouped by risk level + scan controls."""
    from models.job import get_last_scan
    try:
        counts = risk_counts()
    except Exception:
        counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0, "total": 0}
    try:
        last_scan = get_last_scan()
    except Exception:
        last_scan = None
    return render_template("dashboard.html", counts=counts, sources=list_sources(),
                           last_scan=last_scan, total=counts.get("total", 0))


@app.route("/dashboard/jobs/<int:job_id>", methods=["GET"])
@limiter.limit(lambda: config.RATE_LIMIT_READ)
def dashboard_job_detail(job_id):
    """Full stored risk report for one scanned job."""
    try:
        job = get_job(job_id)
    except Exception:
        logger.exception("Dashboard: failed to fetch job %s", job_id)
        return render_template("job_detail.html", job=None,
                               error="Could not load this job report."), 500
    if not job:
        return render_template("job_detail.html", job=None, error="Job not found."), 404
    job.setdefault("risk_categories", [])
    job.setdefault("key_indicators", [])
    job.setdefault("recommended_actions", [])
    job.setdefault("employer_verification", {
        "company_website": "Could not check", "email_domain_match": "N/A",
        "role_on_careers_page": "Unknown", "notes": "",
    })
    return render_template("job_detail.html", job=job, error=None)


# Model loading is deferred to the first analysis request (_ensure_model) so
# that boot, scanner, and dashboard stay fast and light on Render's free tier.

try:
    init_db()
except Exception as exc:
    logger.warning("Could not initialise job database: %s", exc)

# Automatic scheduled scanning (Phase 3). Background daemon thread, so the
# web app never blocks. Skipped in the Werkzeug reloader parent process to
# avoid double-scheduling during development.
if config.SCAN_ENABLED and (not config.FLASK_DEBUG
                            or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    from services import scheduler
    scheduler.start_background()

# One-line startup diagnostic so deploy logs show whether the OCR toolchain is
# present. Image / scanned-PDF uploads need the system Tesseract binary, which
# only exists when the app is deployed from the Dockerfile (see README).
logger.info("OCR toolchain: tesseract=%s (cmd=%r), pdf_render=%s (poppler)",
            ocr_utils.tesseract_available(), ocr_utils.TESSERACT_CMD,
            ocr_utils.PDF2IMAGE_AVAILABLE)

if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
