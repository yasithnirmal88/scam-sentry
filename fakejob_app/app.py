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
"""

import logging
import os
import pickle

import numpy as np
from flask import Flask, request, jsonify, render_template
from scipy.sparse import hstack, csr_matrix

import config
import fraud_features
from fraud_features import extract_all_features, FEATURE_KEYS
from text_processing import preprocess
from ocr_utils import extract_text
from model_training import build_synthetic_dataset, train
from risk.indicators import analyze_indicators
from risk.engine import assess_risk
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

_clf = None
_tfidf = None


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


def vectorize(text):
    cleaned = preprocess(text)
    tfidf_vec = _tfidf.transform([cleaned])
    result = extract_all_features(text)
    rule_vec = csr_matrix(
        np.array([[result["features"].get(k, 0) for k in FEATURE_KEYS]], dtype=float)
    )
    combined = hstack([tfidf_vec, rule_vec]).tocsr()
    return combined, result


def classify(text):
    if not text or len(text.strip()) < config.MIN_TEXT_LENGTH:
        return {
            "error": "Not enough text was found to analyse. Please paste a "
                      "longer job advertisement or upload a clearer file."
        }

    X, rule_result = vectorize(text)
    ml_proba_fake = float(_clf.predict_proba(X)[0][1]) * 100  # 0-100

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
    if rule_result.get("critical_hit"):
        final_score = max(final_score, fraud_features.CRITICAL_SCORE_FLOOR)
    elif rule_result.get("strong_hit"):
        final_score = max(final_score, fraud_features.STRONG_SCORE_FLOOR)

    prediction = "Fake" if final_score >= config.FAKE_THRESHOLD else "Genuine"
    confidence = final_score if prediction == "Fake" else round(100 - final_score, 1)

    if final_score >= config.HIGH_RISK_THRESHOLD:
        risk_level = "HIGH"
    elif final_score >= config.MEDIUM_RISK_THRESHOLD:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

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

    # ---- v1.0 Risk Assessment (primary, per Architecture Upgrade Spec) ----
    # Indicator-driven verdict; hybrid score is a supporting signal only.
    # Critical score-floor: any Critical indicator forces Critical level
    # regardless of ML score (enforced inside assess_risk determination rules).
    fired = analyze_indicators(text)
    assessment = assess_risk(fired)
    verification = verify_employer(text, fired)
    actions = generate_actions(fired, assessment["overall_risk_level"])

    hybrid_01 = round(final_score / 100.0, 3)
    rule_01 = round(rule_score / 100.0, 3)
    ml_01 = round(ml_proba_fake / 100.0, 3)

    return {
        # New structured response (primary).
        "overall_risk_level": assessment["overall_risk_level"],
        "risk_categories": assessment["risk_categories"],
        "confidence": assessment["confidence"],
        "summary": assessment["summary"],
        "key_indicators": assessment["key_indicators"],
        "employer_verification": verification,
        "recommended_actions": actions,
        "hybrid_score": hybrid_01,
        "rule_score": rule_01,
        "ml_score": ml_01,
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
def analyze_text():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    result = classify(text)
    if "error" in result:
        return jsonify(result), 400
    result["source"] = "pasted-text"
    return jsonify(result)


@app.route("/api/analyze/file", methods=["POST"])
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
    try:
        extracted_text, method = extract_text(file.filename, file_bytes)
    except Exception as exc:
        return jsonify({"error": f"Could not read the file: {exc}"}), 400

    result = classify(extracted_text)
    if "error" in result:
        return jsonify(result), 400
    result["source"] = f"file-upload ({method})"
    return jsonify(result)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "model_loaded": _clf is not None})


# ---------------------------------------------------------------------------
# Job Risk Scanner API (Phase 1)
# ---------------------------------------------------------------------------

@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    """List scanned jobs. Query params: risk_level, source, q, limit, offset."""
    try:
        jobs = list_jobs(
            risk_level=request.args.get("risk_level"),
            source=request.args.get("source"),
            query=request.args.get("q"),
            limit=request.args.get("limit", 50),
            offset=request.args.get("offset", 0),
        )
        return jsonify({
            "jobs": jobs,
            "total": count_jobs(),
            "counts": risk_counts(),
        })
    except Exception as exc:
        logger.exception("Failed to list jobs")
        return jsonify({"error": f"Could not list jobs: {exc}"}), 500


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def api_get_job(job_id):
    """Full details of one job, including its stored risk report."""
    try:
        job = get_job(job_id)
    except Exception as exc:
        logger.exception("Failed to fetch job %s", job_id)
        return jsonify({"error": f"Could not fetch job: {exc}"}), 500
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.route("/api/scan", methods=["POST"])
def api_trigger_scan():
    """Trigger a scan manually. Body (JSON, optional): {sources: [...], limit: N}.

    Runs in a background thread (202) so the web app never blocks.
    Pass ?sync=1 (or {"sync": true}) to wait for completion instead.
    """
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
        except Exception as exc:
            logger.exception("Scan failed")
            return jsonify({"error": f"Scan failed: {exc}"}), 500
        summary["counts"] = risk_counts()
        return jsonify(summary)

    result = scheduler.trigger_async(sources=sources, limit=limit)
    if not result.get("accepted"):
        return jsonify(result), 409
    return jsonify(result), 202


@app.route("/api/scan/status", methods=["GET"])
def api_scan_status():
    """Current scan state (running/idle) + last recorded run."""
    from services import scheduler
    try:
        return jsonify(scheduler.get_status())
    except Exception as exc:
        logger.exception("Failed to get scan status")
        return jsonify({"error": f"Could not get scan status: {exc}"}), 500


@app.route("/api/sources", methods=["GET"])
def api_list_sources():
    return jsonify({"sources": list_sources()})


# ---------------------------------------------------------------------------
# Job Risk Dashboard (Phase 2, server-rendered pages on top of the API)
# ---------------------------------------------------------------------------

@app.route("/dashboard", methods=["GET"])
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
def dashboard_job_detail(job_id):
    """Full stored risk report for one scanned job."""
    try:
        job = get_job(job_id)
    except Exception as exc:
        logger.exception("Dashboard: failed to fetch job %s", job_id)
        return render_template("job_detail.html", job=None, error=str(exc)), 500
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


load_or_train_model()

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

if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
