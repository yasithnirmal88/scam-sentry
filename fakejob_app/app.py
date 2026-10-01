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

import os
import pickle

import numpy as np
from flask import Flask, request, jsonify, render_template
from scipy.sparse import hstack, csr_matrix

import fraud_features
from fraud_features import extract_all_features, FEATURE_KEYS
from text_processing import preprocess
from ocr_utils import extract_text
from model_training import build_synthetic_dataset, train, MODEL_DIR

APP_DIR = os.path.dirname(__file__)
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

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
        print("No trained model found - training on a fresh synthetic dataset "
              "(first run only, takes a few seconds)...")
        df = build_synthetic_dataset(n_per_class=450)
        train(df)

    with open(clf_path, "rb") as f:
        _clf = pickle.load(f)
    with open(tfidf_path, "rb") as f:
        _tfidf = pickle.load(f)
    print("Model loaded.")


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
    if not text or len(text.strip()) < 15:
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
    final_score = round(0.55 * rule_score + 0.45 * ml_proba_fake, 1)

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

    prediction = "Fake" if final_score >= 50 else "Genuine"
    confidence = final_score if prediction == "Fake" else round(100 - final_score, 1)

    if final_score >= 65:
        risk_level = "HIGH"
    elif final_score >= 35:
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

    return {
        "prediction": prediction,
        "confidence_score": confidence,
        "fake_probability": final_score,
        "risk_level": risk_level,
        "ml_probability": round(ml_proba_fake, 1),
        "rule_score": rule_score,
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


load_or_train_model()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
