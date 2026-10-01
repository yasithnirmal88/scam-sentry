# Scam Sentry — Intelligent Fake Job Advertisement Detection System

A fully working implementation of the Group 44 project proposal
("Intelligent Fake Job Advertisement Detection System Using AI"),
built as a **hybrid** detector (rule-based fraud indicators + ML text
classifier) rather than a pure word-association model — this fixes the
"assistant → fake" style shortcut-learning problem described in the
project's own testing notes.

## What it does

1. **Input** — paste job ad text, or upload a PDF / JPG / PNG.
2. **OCR** — `pytesseract` reads images; `pdfplumber` extracts PDF text,
   falling back to `pdf2image` + OCR for scanned PDFs with no text layer.
3. **NLP preprocessing** — tokenization, stop-word removal, lowercasing,
   punctuation stripping, normalization (`text_processing.py`).
4. **Feature extraction** — two parallel tracks, combined:
   - `TfidfVectorizer` text features.
   - **Explicit fraud-indicator features** (`fraud_features.py`):
     payment requests, requests for sensitive/banking info, free email
     domains, urgency language, unrealistic benefit claims, suspicious
     links, missing company/location info, unrealistically high salary
     for "no experience" roles, and vague/generic descriptions.
5. **Classification** — a `GradientBoostingClassifier` (the sklearn
   drop-in used here since `xgboost` can't be installed in this sandbox
   — swap back to `xgboost.XGBClassifier()` in `model_training.py` with
   one line if you have it available) trained on the combined feature
   vector.
6. **Hybrid scoring** — the final risk score blends the transparent
   rule-based score with the ML model's probability, so the verdict is
   never a black box.
7. **Explanation** — instead of raw SHAP word dumps (e.g. `"assistant"`,
   `"skill"`), the UI lists the actual evidence: *Payment Request*,
   *Sensitive Information Request*, *Free Email Provider*, etc., each
   with a plain-English reason and a severity badge.

## Project structure

```
fakejob_app/
├── app.py                # Flask backend + REST API
├── fraud_features.py     # Rule-based fraud indicator detectors
├── text_processing.py    # NLP preprocessing pipeline
├── ocr_utils.py           # PDF/image text extraction (OCR)
├── model_training.py      # Dataset generation + model training
├── requirements.txt
├── model/                 # Saved model artifacts (auto-generated)
├── templates/
│   └── index.html
└── static/
    ├── style.css
    └── script.js
```

## Running it locally

### 1. System dependencies (install once, outside pip)

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr poppler-utils

# macOS
brew install tesseract poppler
```
On Windows, install Tesseract-OCR and Poppler and add both to your PATH.

### 2. Python dependencies

```bash
cd fakejob_app
python3 -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Run

```bash
python3 app.py
```

Open **http://localhost:5000** in your browser.

On first run, the app automatically trains the model (a few seconds)
using a balanced synthetic dataset and saves it to `model/`. Subsequent
runs load the saved model instantly.

## Using the real Kaggle dataset instead of the synthetic one

The proposal specifies the Kaggle **EMSCAD Fake Job Postings** dataset.
This sandbox has no internet access, so a synthetic, deliberately
*balanced* dataset is generated instead (same job titles appear in both
genuine and fake examples — only real fraud indicators determine the
label, avoiding job-title bias).

To train on the real dataset:

```bash
# 1. Download fake_job_postings.csv from:
#    https://www.kaggle.com/datasets/shivamb/real-or-fake-fake-jobposting-prediction
# 2. Place it in fakejob_app/data/fake_job_postings.csv
# 3. Run:
python3 model_training.py --real data/fake_job_postings.csv
# 4. Restart the app — it will load the newly trained model.
```

## API reference

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/analyze/text` | POST | `{"text": "..."}` | verdict JSON |
| `/api/analyze/file` | POST | multipart `file` (pdf/png/jpg) | verdict JSON |
| `/api/health` | GET | — | `{"status": "ok"}` |

Example verdict response:

```json
{
  "prediction": "Fake",
  "confidence_score": 76.9,
  "fake_probability": 76.9,
  "risk_level": "HIGH",
  "rule_score": 58,
  "ml_probability": 100.0,
  "indicators": [
    {
      "label": "Payment Request",
      "severity": "HIGH",
      "detail": "The advertisement asks the applicant to pay a fee, deposit, or send money before or during the hiring process."
    }
  ],
  "company_detected": null,
  "source": "pasted-text"
}
```

## Notes / honest limitations

- **XGBoost → GradientBoostingClassifier**: functionally equivalent
  gradient-boosted trees; swap back to XGBoost trivially if the package
  is available in your environment.
- **SHAP → rule-based explanation engine**: this was a deliberate
  upgrade, not just a substitution — SHAP over raw TF-IDF words was
  producing meaningless/misleading explanations (e.g. "assistant" →
  fraudulent). The engineered-feature explanation is both more honest
  and easier for end users to act on. You can still add SHAP on top of
  the `GradientBoostingClassifier` later if you want feature-importance
  plots for your report/viva.
- **Dataset**: synthetic by default (see above for plugging in the real
  Kaggle data). The rule engine's keyword lists are a reasonable starting
  set — extend `fraud_features.py` with more patterns/locale-specific
  phrasing as you gather real examples.
- **Frontend**: implemented in vanilla HTML/CSS/JS (Flask-rendered)
  rather than a separate React app, so the whole system runs with a
  single `python app.py` — the API layer is already clean JSON, so it
  can be swapped for a React frontend later without touching the backend.
