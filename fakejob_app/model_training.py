"""
model_training.py
------------------
Builds a BALANCED training dataset and trains the hybrid classifier
(TF-IDF text features + engineered fraud-indicator features -> classifier).

IMPORTANT NOTE ON THE DATASET
------------------------------
The project proposal specifies training on the Kaggle "Fake Job Postings"
(EMSCAD) dataset. This environment has no internet access, so that file
cannot be downloaded here. To keep the system fully working out of the box,
this script instead generates a large, *balanced* synthetic dataset: the
same job titles appear in BOTH genuine and fake examples, and only the
presence/absence of real fraud indicators (payment requests, sensitive-info
requests, free email domains, urgency language, vague descriptions, etc.)
determines the label. This directly avoids the failure mode described in
the project's own analysis, where a model trained on an imbalanced dataset
learns spurious "job-title -> label" shortcuts (e.g. "assistant" -> fake)
instead of real fraud characteristics.

TO USE THE REAL KAGGLE DATASET INSTEAD:
  1. Download `fake_job_postings.csv` from Kaggle (EMSCAD dataset).
  2. Place it at data/fake_job_postings.csv (recognised text columns include
     title / company_profile / description / requirements / benefits; the
     label column is `fraudulent`), or pass an explicit path.
  3. Train:     python model_training.py --real data/fake_job_postings.csv
     Evaluate:  python model_training.py --eval-only --real data/fake_job_postings.csv
     Compare:   python model_training.py --compare --real data/fake_job_postings.csv

Without `--real` the script trains on the synthetic set and the metadata says
so. Real-data mode records `source="real"`, the dataset name, class
distribution, and hold-out metrics in artifacts/meta.pkl. `--eval-only` and
`--compare` never overwrite the committed artifacts.
"""

import argparse
import logging
import os
import pickle
import random
import re
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
from sklearn import __version__ as _sklearn_version
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (classification_report, accuracy_score,
                             precision_recall_fscore_support, f1_score)
from scipy.sparse import hstack, csr_matrix

from fraud_features import extract_all_features, FEATURE_KEYS
from text_processing import preprocess

try:
    import config
    MODEL_DIR = config.MODEL_DIR
    _TFIDF_MAX_FEATURES = config.TFIDF_MAX_FEATURES
    _TFIDF_NGRAM_RANGE = config.TFIDF_NGRAM_RANGE
    _GBC_N_ESTIMATORS = config.GBC_N_ESTIMATORS
    _GBC_MAX_DEPTH = config.GBC_MAX_DEPTH
    _GBC_LEARNING_RATE = config.GBC_LEARNING_RATE
    _GBC_LEARNING_RATE = config.GBC_LEARNING_RATE
    _SYNTHETIC_N_PER_CLASS = config.SYNTHETIC_SAMPLES_PER_CLASS
    _REAL_DATASET_PATH = config.REAL_DATASET_PATH
except ImportError:  # standalone script use without config on path
    MODEL_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
    _TFIDF_MAX_FEATURES = 800
    _TFIDF_NGRAM_RANGE = (1, 2)
    _GBC_N_ESTIMATORS = 120
    _GBC_MAX_DEPTH = 3
    _GBC_LEARNING_RATE = 0.08
    _SYNTHETIC_N_PER_CLASS = 450
    _REAL_DATASET_PATH = os.path.join(
        os.path.dirname(__file__), "data", "fake_job_postings.csv")

random.seed(42)
np.random.seed(42)

os.makedirs(MODEL_DIR, exist_ok=True)

JOB_TITLES = [
    "Software Engineer", "Administrative Assistant", "Data Entry Clerk",
    "Customer Service Representative", "Marketing Executive",
    "Graphic Designer", "Accountant", "IT Support Technician",
    "Sales Executive", "Human Resource Officer", "Web Developer",
    "Content Writer", "Virtual Assistant", "Warehouse Associate",
    "Data Scientist", "Project Coordinator", "Receptionist",
    "Digital Marketing Specialist", "Business Analyst", "Nurse",
    "Teacher", "Delivery Driver", "Financial Analyst", "Social Media Manager",
    "Operations Manager", "Quality Assurance Tester", "Network Administrator",
    "Executive Assistant", "Bookkeeper", "Recruiter",
    "Staff Software Engineer", "Senior Product Manager", "UX Researcher",
    "DevOps Engineer", "Legal Counsel", "Supply Chain Analyst",
]

COMPANIES = [
    "Ceylon Tech Solutions", "Global Innovate Ltd", "Bright Path Recruiters",
    "NextGen Software", "Skyline Logistics", "Prime Financial Group",
    "Horizon Marketing Agency", "BlueWave Systems", "Everest Consultants",
    "Orion Data Services", "Meridian Games Inc", "Falcon Robotics Corp",
    "Lantern Health LLC", "Cobalt Studios", "Redwood Analytics",
]

LOCATIONS = [
    "Colombo, Sri Lanka", "Kandy, Sri Lanka", "Remote", "Los Angeles, USA",
    "New York, USA", "London, UK", "Toronto, Canada", "Singapore",
    "Mercer Island, USA", "Berlin, Germany", "Sydney, Australia",
]

GENUINE_RESPONSIBILITIES = [
    "Develop and maintain REST APIs using modern frameworks",
    "Prepare monthly financial statements and reconcile accounts",
    "Respond to customer inquiries via phone and email within SLA",
    "Design marketing collateral and manage the social media calendar",
    "Coordinate project timelines and track deliverables using Jira",
    "Provide first-line IT support and troubleshoot hardware issues",
    "Maintain accurate records in the HR information system",
    "Analyse sales data and prepare quarterly performance reports",
    "Write and edit content for the company blog and newsletters",
    "Perform quality assurance testing on new software releases",
    "Lead architecture discussions and mentor junior engineers",
    "Partner with cross-functional stakeholders to define requirements",
    "Own the roadmap for a core product area end to end",
    "Drive root-cause analysis for production incidents",
    "Review pull requests and uphold engineering best practices",
]

GENUINE_QUALIFICATIONS = [
    "Bachelor's degree in a relevant field and 2+ years of experience",
    "Proficiency in Microsoft Office and strong communication skills",
    "Experience with SQL, Python, or similar tools preferred",
    "Diploma or degree with at least 1 year of relevant experience",
    "Strong attention to detail and ability to meet deadlines",
    "5+ years of industry experience with a track record of technical leadership",
    "Excellent written and verbal communication across cross-functional teams",
    "Comparable practical experience will also be considered in lieu of a degree",
]

# Sign-off / contact-instruction variants -- deliberately varied so the
# model cannot key off one literal phrase as "the" genuine signature.
GENUINE_SIGNOFFS = [
    "Please apply with your CV to careers@{domain}.",
    "Interested candidates should submit their resume through our careers portal.",
    "To apply, use the 'Apply Now' button on this listing.",
    "Qualified candidates can apply directly on our website.",
    "Send your application, including a short cover letter, to jobs@{domain}.",
    "Applications are reviewed on a rolling basis via our official careers page.",
    "",  # some real postings simply have no explicit sign-off line at all
]

# Long-form corporate boilerplate blocks, appended to a portion of genuine
# samples so the model sees realistic EEO/benefits/salary-disclosure text
# as normal, rather than treating any posting that isn't short and
# templated as suspicious.
EEO_BLOCKS = [
    "It is our policy to provide equal employment opportunity to all "
    "applicants without regard to race, color, religion, sex, sexual "
    "orientation, gender identity, national origin, age, or disability.",
    "We are an equal opportunity employer and value diversity. All "
    "employment decisions are based on qualifications, merit, and "
    "business need.",
    "We celebrate diversity and are committed to creating an inclusive "
    "environment for all employees, and do not discriminate on the "
    "basis of any protected characteristic.",
]
BENEFITS_BLOCKS = [
    "We offer medical, dental, and life insurance, a retirement savings "
    "plan with company match, and generous paid time off.",
    "Our perks include flexible work schedules, parental leave, wellness "
    "stipends, and ongoing learning and development budgets.",
    "Benefits include comprehensive health coverage, equity, and an "
    "open vacation policy.",
]
SALARY_DISCLOSURE_BLOCKS = [
    "Base salary range: {low} - {high} USD, plus incentive compensation "
    "and equity, depending on experience and location.",
    "The pay range for this role is {low} - {high} USD per year, "
    "commensurate with experience.",
]

GENERIC_FILLERS_GENUINE = [
    "", "", "",  # most genuine posts do NOT lean on buzzwords
    "We value collaboration, curiosity, and craftsmanship in everything we build.",
]

FAKE_HOOKS = [
    "Applicants must pay a refundable registration fee of {amt} before the interview.",
    "Please send your bank account number and NIC copy to confirm your slot.",
    "Limited positions available - apply within 24 hours or miss this opportunity!",
    "Earn {salary} per month with no experience required, guaranteed income from day one.",
    "Contact our recruiter directly at {freeemail} for urgent processing.",
    "A small training kit fee is required before we can process your application.",
    "100% guaranteed job placement, act now, only 3 seats left today!",
    "Send your passport number and a copy of your bank card for verification purposes.",
    "A refundable security deposit of {amt} secures your position immediately.",
    "We will WhatsApp you the next steps once the processing fee is received.",
]

FAKE_PROFESSIONAL_FILLER = [
    "We are a fast-growing international company expanding our remote workforce.",
    "This is a fully remote opportunity open to candidates worldwide.",
    "Our client, a leading multinational firm, is urgently expanding their team.",
    "This role offers flexible hours and the chance to work with a global brand.",
]

GENERIC_FILLERS_FAKE = [
    "Join our amazing team and work on exciting projects in a dynamic environment.",
    "We are looking for a passionate self starter to join our great opportunity.",
    "Be your own boss and enjoy unlimited earning potential from home.",
]


def _rand_domain(company):
    return re.sub(r"[^a-z0-9]", "", company.lower()) + ".com"


def _genuine_sample():
    title = random.choice(JOB_TITLES)
    company = random.choice(COMPANIES)
    location = random.choice(LOCATIONS)
    domain = _rand_domain(company)

    style = random.choice(["labeled", "prose_at", "prose_leading", "header_line"])

    resp = ". ".join(random.sample(GENUINE_RESPONSIBILITIES, k=random.randint(2, 4)))
    quals = ". ".join(random.sample(GENUINE_QUALIFICATIONS, k=random.randint(1, 2)))
    filler = random.choice(GENERIC_FILLERS_GENUINE)
    signoff = random.choice(GENUINE_SIGNOFFS).format(domain=domain)

    if style == "labeled":
        body = (
            f"Job Title: {title}\nCompany: {company}\nLocation: {location}\n"
            f"We are hiring a {title} to join our team. Responsibilities: {resp}.\n"
            f"Requirements: {quals}.\n{filler}\n{signoff}"
        )
    elif style == "prose_at":
        body = (
            f"{title}\n{location}\n\n"
            f"As a {title} at {company}, you will {resp[0].lower()}{resp[1:]}. "
            f"{filler}\n\nWhat you'll need: {quals}.\n{signoff}"
        )
    elif style == "prose_leading":
        body = (
            f"{company} is looking for a talented {title} based in {location}. "
            f"In this role you will: {resp}. {filler}\n\n"
            f"What we're looking for: {quals}.\n{signoff}"
        )
    else:  # header_line, mimics real ATS postings like the Riot example
        body = (
            f"{title}\n{location}\nAdditional Locations: {random.choice(LOCATIONS)}\n\n"
            f"Job Id: REQ-{random.randint(1000,9999)}\n\n"
            f"{company} is a company that values {random.choice(['craft', 'ownership', 'collaboration'])}. "
            f"As a {title}, you will partner closely with the wider team. {resp}.\n\n"
            f"Required Qualifications:\n{quals}\n\n{signoff}"
        )

    # Randomly append realistic corporate boilerplate to part of the set,
    # so long, legally-worded, benefits-and-EEO-heavy postings are learned
    # as a NORMAL genuine pattern rather than an anomaly.
    if random.random() < 0.45:
        body += "\n\n" + random.choice(EEO_BLOCKS)
    if random.random() < 0.45:
        body += "\n\n" + random.choice(BENEFITS_BLOCKS)
    if random.random() < 0.4:
        low = random.choice([45000, 65000, 90000, 120000, 150000, 190000])
        high = low + random.choice([15000, 30000, 60000, 80000])
        body += "\n\n" + random.choice(SALARY_DISCLOSURE_BLOCKS).format(low=f"${low:,}", high=f"${high:,}")

    return body.strip()


def _fake_sample():
    title = random.choice(JOB_TITLES)
    use_company = random.random() > 0.4
    company = random.choice(COMPANIES) if use_company else None
    n_hooks = random.randint(1, 3)
    hooks = random.sample(FAKE_HOOKS, k=n_hooks)
    filler = random.choice(GENERIC_FILLERS_FAKE)
    free_email = random.choice(["quickjobs99@gmail.com", "hr.jobs2024@gmail.com",
                                 "recruitment.team@yahoo.com", "apply.now@hotmail.com"])
    amt_options = ["LKR 25,000", "LKR 15,000", "$150", "$300", "LKR 40,000"]
    salary_options = ["LKR 250,000", "LKR 300,000", "$8,000", "$6,500"]

    lines = [f"{title}"]
    if company:
        lines.append(f"{company}")
    if random.random() < 0.5:
        lines.append(random.choice(FAKE_PROFESSIONAL_FILLER))
    lines.append(filler)
    for h in hooks:
        lines.append(h.format(amt=random.choice(amt_options),
                               salary=random.choice(salary_options),
                               freeemail=free_email))
    if random.random() > 0.5:
        lines.append("No experience required, freshers welcome to apply immediately.")
    if random.random() < 0.3:
        # occasionally wrap the hooks in a longer, more "professional"
        # sounding paragraph so length/tone alone can't be used as a
        # genuine/fake signal by the model.
        lines.append("We pride ourselves on a fast, streamlined hiring process "
                      "designed to get great candidates started quickly.")
    text = "\n".join(lines)
    return text.strip()


def build_synthetic_dataset(n_per_class=450):
    rows = []
    for _ in range(n_per_class):
        rows.append({"text": _genuine_sample(), "label": 0})
    for _ in range(n_per_class):
        rows.append({"text": _fake_sample(), "label": 1})
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset="text").reset_index(drop=True)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    return df


# Columns commonly present in EMSCAD / Kaggle `fake_job_postings.csv`. Only
# those actually present are used, so slightly different exports still work.
_TEXT_COLUMN_CANDIDATES = (
    "title", "company_profile", "description", "requirements", "benefits",
    "location", "employment_type", "required_experience", "required_education",
    "industry", "function",
)
_LABEL_COLUMN_CANDIDATES = ("fraudulent", "label", "is_fake", "is_fraudulent")
# Rows whose combined text is shorter than this are treated as unusable.
_MIN_REAL_TEXT_CHARS = 10


def _build_text_column(df):
    """Join whatever useful text columns exist into a single `text` field."""
    cols = [c for c in _TEXT_COLUMN_CANDIDATES if c in df.columns]
    if not cols:
        raise ValueError(
            "real dataset has no recognised text columns; expected at least "
            "one of: " + ", ".join(_TEXT_COLUMN_CANDIDATES))
    return (df[cols].fillna("").astype(str)
            .apply(lambda row: " ".join(p.strip() for p in row if p.strip()),
                   axis=1))


def _find_label_column(df):
    for col in _LABEL_COLUMN_CANDIDATES:
        if col in df.columns:
            return col
    raise ValueError(
        "real dataset has no label column; expected one of: "
        + ", ".join(_LABEL_COLUMN_CANDIDATES))


def load_real_dataset(path):
    """Load and clean an EMSCAD-style CSV into `text` + integer `label`.

    `label` is 1 for fraudulent postings and 0 for genuine ones. The text
    field is built from whichever known columns are present (title,
    company_profile, description, requirements, benefits, ...). Rows with an
    unusable label or empty/too-short text are dropped, and duplicate texts
    removed.

    Raises FileNotFoundError (with placement instructions) when the file is
    absent, and ValueError when required columns/classes are missing.
    """
    path = str(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Real dataset not found at: %s\n"
            "Download the EMSCAD/Kaggle 'fake_job_postings.csv', place it under "
            "fakejob_app/data/fake_job_postings.csv, or pass an explicit path "
            "with `--real /path/to/fake_job_postings.csv` (or set the "
            "REAL_DATASET_PATH env var)." % path)

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Real dataset at %s is empty." % path)

    label_col = _find_label_column(df)
    df = df.copy()
    df["text"] = _build_text_column(df)
    df["label"] = pd.to_numeric(df[label_col], errors="coerce")

    before = len(df)
    df = df[df["label"].isin([0, 1])]
    df = df[df["text"].str.strip().str.len() >= _MIN_REAL_TEXT_CHARS]
    df = df.drop_duplicates(subset=["text"]).reset_index(drop=True)
    df["label"] = df["label"].astype(int)

    if df.empty:
        raise ValueError(
            "Real dataset at %s has no usable rows after cleaning." % path)
    if df["label"].nunique() < 2:
        raise ValueError(
            "Real dataset at %s has only one class after cleaning; need both "
            "genuine and fraudulent postings to evaluate." % path)

    n_fake = int((df["label"] == 1).sum())
    n_genuine = int((df["label"] == 0).sum())
    logger.info("Loaded real dataset '%s': %d usable rows "
                "(genuine=%d, fake=%d); dropped %d invalid/duplicate.",
                os.path.basename(path), len(df), n_genuine, n_fake,
                before - len(df))
    return df[["text", "label"]]


def build_feature_matrix(texts, tfidf: TfidfVectorizer, fit=False):
    cleaned = [preprocess(t) for t in texts]
    if fit:
        tfidf_matrix = tfidf.fit_transform(cleaned)
    else:
        tfidf_matrix = tfidf.transform(cleaned)

    rule_rows = []
    for t in texts:
        result = extract_all_features(t)
        rule_rows.append([result["features"].get(k, 0) for k in FEATURE_KEYS])
    rule_matrix = csr_matrix(np.array(rule_rows, dtype=float))

    combined = hstack([tfidf_matrix, rule_matrix]).tocsr()
    return combined


def _compute_metrics(y_true, preds, n_train=None, n_test=None):
    """Per-class + macro/weighted hold-out metrics. `Fake` is label 1."""
    acc = accuracy_score(y_true, preds)
    prec, rec, f1, support = precision_recall_fscore_support(
        y_true, preds, labels=[0, 1], zero_division=0)
    metrics = {
        "accuracy": round(float(acc), 4),
        "precision_fake": round(float(prec[1]), 4),
        "recall_fake": round(float(rec[1]), 4),
        "f1_fake": round(float(f1[1]), 4),
        "precision_genuine": round(float(prec[0]), 4),
        "recall_genuine": round(float(rec[0]), 4),
        "f1_genuine": round(float(f1[0]), 4),
        "f1_macro": round(float(f1_score(y_true, preds, average="macro",
                                         zero_division=0)), 4),
        "f1_weighted": round(float(f1_score(y_true, preds, average="weighted",
                                            zero_division=0)), 4),
        "support_genuine": int(support[0]),
        "support_fake": int(support[1]),
    }
    if n_train is not None:
        metrics["n_train"] = int(n_train)
    if n_test is not None:
        metrics["n_test"] = int(n_test)
    return metrics


def _log_metrics(metrics, source):
    logger.info("Hold-out metrics (%s, Fake = positive class):", source)
    logger.info("  accuracy=%.4f  precision=%.4f  recall=%.4f  f1=%.4f",
                metrics["accuracy"], metrics["precision_fake"],
                metrics["recall_fake"], metrics["f1_fake"])
    logger.info("  f1_macro=%.4f  f1_weighted=%.4f  n_test=%s",
                metrics["f1_macro"], metrics["f1_weighted"],
                metrics.get("n_test"))


def _log_honesty(source, dataset_name):
    if source == "synthetic":
        logger.info(
            "HONESTY NOTE: the synthetic classes are near-separable, so these "
            "metrics overstate real-world performance and are NOT a claim about "
            "performance on real job postings.")
    else:
        logger.info(
            "HONESTY NOTE: metrics come from a held-out split of real data "
            "(%s). Real-world metrics are more meaningful than synthetic ones, "
            "but they reflect that dataset's bias (largely English-language "
            "postings) and are not a production fraud-detection claim. The "
            "deterministic Risk Engine, not the ML model, sets the verdict; ML "
            "is a supporting signal only.", dataset_name or "real data")


def train(dataset: pd.DataFrame, model_dir=MODEL_DIR, source="synthetic",
          dataset_name=None):
    X_text = dataset["text"].tolist()
    y = dataset["label"].values

    tfidf = TfidfVectorizer(max_features=_TFIDF_MAX_FEATURES, ngram_range=_TFIDF_NGRAM_RANGE, min_df=3,
                             max_df=0.85, sublinear_tf=True)
    cleaned = [preprocess(t) for t in X_text]
    tfidf.fit(cleaned)

    X = build_feature_matrix(X_text, tfidf, fit=False)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # GradientBoostingClassifier used as the sklearn-native stand-in for
    # XGBoost (XGBoost itself cannot be installed in this offline sandbox;
    # swap in xgboost.XGBClassifier() as a drop-in replacement in an
    # environment with internet access / the package installed).
    # subsample < 1 and a min_samples_leaf floor keep it from memorizing
    # incidental phrasing in a synthetic dataset.
    clf = GradientBoostingClassifier(
        n_estimators=_GBC_N_ESTIMATORS, max_depth=_GBC_MAX_DEPTH, learning_rate=_GBC_LEARNING_RATE, subsample=0.8,
        min_samples_leaf=5, random_state=42
    )
    clf.fit(X_train, y_train)

    preds = clf.predict(X_test)
    metrics = _compute_metrics(y_test, preds, n_train=X_train.shape[0],
                               n_test=X_test.shape[0])
    _log_metrics(metrics, source)
    logger.info("Classification report:\n%s",
                classification_report(y_test, preds,
                                      target_names=["Genuine", "Fake"],
                                      zero_division=0))
    _log_honesty(source, dataset_name)

    with open(os.path.join(model_dir, "classifier.pkl"), "wb") as f:
        pickle.dump(clf, f)
    with open(os.path.join(model_dir, "tfidf.pkl"), "wb") as f:
        pickle.dump(tfidf, f)

    if source == "synthetic":
        honesty_note = (
            "Metrics are measured on a held-out split of synthetic data whose "
            "classes are near-separable; they are NOT an estimate of real-world "
            "performance. The Risk Engine, not this model, sets the verdict.")
    else:
        honesty_note = (
            "Metrics are measured on a held-out split of the real dataset "
            "'%s'. Real-world numbers are more meaningful than synthetic ones, "
            "but they reflect that dataset's bias (largely English-language "
            "postings) and are not a production fraud-detection claim. The "
            "deterministic Risk Engine, not this model, sets the verdict; ML is "
            "a supporting signal only." % (dataset_name or "real data"))

    n_fake = int((dataset["label"] == 1).sum())
    n_genuine = int((dataset["label"] == 0).sum())
    meta = {
        "source": source,
        "dataset": dataset_name or ("synthetic-generator" if source == "synthetic"
                                    else "unknown"),
        "class_distribution": {"genuine": n_genuine, "fake": n_fake},
        "estimator": "GradientBoostingClassifier",
        "sklearn_version": _sklearn_version,
        "n_samples": len(dataset),
        "n_features": int(X.shape[1]),
        "validation_accuracy": float(metrics["accuracy"]),
        "metrics": metrics,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_estimators": _GBC_N_ESTIMATORS,
        "max_depth": _GBC_MAX_DEPTH,
        "learning_rate": _GBC_LEARNING_RATE,
        "honesty_note": honesty_note,
    }
    with open(os.path.join(model_dir, "meta.pkl"), "wb") as f:
        pickle.dump(meta, f)

    logger.info("Saved model artifacts to %s/", model_dir)
    return clf, tfidf


def load_artifacts(model_dir=MODEL_DIR):
    """Load the persisted classifier + vectorizer (raises if absent)."""
    with open(os.path.join(model_dir, "classifier.pkl"), "rb") as f:
        clf = pickle.load(f)
    with open(os.path.join(model_dir, "tfidf.pkl"), "rb") as f:
        tfidf = pickle.load(f)
    return clf, tfidf


def evaluate_on_dataset(dataset: pd.DataFrame, model_dir=MODEL_DIR,
                        test_size=0.2, dataset_name=None):
    """Evaluate already-saved artifacts on a real dataset's held-out split.

    Does NOT write artifacts. Returns the metrics dict. Used by `--eval-only`
    so reviewers can report real-data metrics without overwriting the
    committed model.
    """
    clf, tfidf = load_artifacts(model_dir)
    X = build_feature_matrix(dataset["text"].tolist(), tfidf, fit=False)
    y = dataset["label"].values
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y)
    preds = clf.predict(X_test)
    metrics = _compute_metrics(y_test, preds, n_test=X_test.shape[0])
    _log_metrics(metrics, "real (eval-only)")
    logger.info("Classification report:\n%s",
                classification_report(y_test, preds,
                                      target_names=["Genuine", "Fake"],
                                      zero_division=0))
    _log_honesty("real", dataset_name)
    return metrics


def compare_models(real_path, n_per_class=_SYNTHETIC_N_PER_CLASS):
    """Train synthetic and real models into scratch dirs and log both metric
    sets for side-by-side comparison. Never touches the committed artifacts."""
    import tempfile
    with tempfile.TemporaryDirectory() as syn_dir, \
            tempfile.TemporaryDirectory() as real_dir:
        logger.info("=== SYNTHETIC-TRAINED MODEL (not a real-world estimate) ===")
        syn = build_synthetic_dataset(n_per_class=n_per_class)
        train(syn, model_dir=syn_dir, source="synthetic",
              dataset_name="synthetic-generator")
        logger.info("=== REAL-DATA-TRAINED MODEL (%s) ===",
                    os.path.basename(str(real_path)))
        real = load_real_dataset(real_path)
        train(real, model_dir=real_dir, source="real",
              dataset_name=os.path.basename(str(real_path)))
    logger.info("Comparison complete. Real-data metrics are the meaningful "
                "ones; synthetic metrics are only a pipeline sanity check. The "
                "Risk Engine remains authoritative and ML stays a supporting "
                "signal.")


@lru_cache(maxsize=1)
def load_model_metadata(model_dir=MODEL_DIR):
    """Model provenance for honest labeling. Never raises; reports absence."""
    base = {
        "available": False,
        "source": "unknown",
        "dataset": None,
        "class_distribution": None,
        "estimator": "unknown",
        "n_samples": 0,
        "n_features": 0,
        "validation_accuracy": None,
        "trained_at_utc": None,
        "sklearn_version": None,
        "metrics": None,
        "honesty_note": None,
    }
    path = os.path.join(model_dir, "meta.pkl")
    if not os.path.exists(path):
        return base
    try:
        with open(path, "rb") as f:
            meta = pickle.load(f)
        base.update({k: v for k, v in meta.items() if k in base})
        base["available"] = True
        return base
    except Exception:
        return base


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train / evaluate the Scam Sentry hybrid classifier and "
                    "write an honest model card (meta.pkl). The Risk Engine, "
                    "not this model, sets the verdict.")
    parser.add_argument("--real", nargs="?", const=_REAL_DATASET_PATH,
                        default=None,
                        help="Train on an EMSCAD/Kaggle fake_job_postings.csv. "
                             "Pass a path, or use --real alone to read the "
                             "default path (%s). Omit it for synthetic "
                             "training." % _REAL_DATASET_PATH)
    parser.add_argument("--n_per_class", type=int, default=_SYNTHETIC_N_PER_CLASS,
                        help="Synthetic samples per class when no real dataset "
                             "is given (default: config.SYNTHETIC_SAMPLES_PER_CLASS)")
    parser.add_argument("--eval-only", action="store_true",
                        help="Evaluate the CURRENT saved artifacts on the real "
                             "dataset and print metrics; no retraining, no "
                             "artifact writes.")
    parser.add_argument("--compare", action="store_true",
                        help="Train synthetic and real models in scratch dirs "
                             "and print both metric sets; committed artifacts "
                             "are left untouched.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    def _load_real_or_die(path):
        try:
            return load_real_dataset(path)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))

    if args.eval_only:
        if not args.real:
            parser.error("--eval-only requires --real [path] to know which "
                         "real dataset to evaluate on.")
        dataset = _load_real_or_die(args.real)
        logger.info("EVAL-ONLY: evaluating the saved model in %s on %s "
                    "(no artifacts will be modified).", MODEL_DIR, args.real)
        evaluate_on_dataset(dataset, model_dir=MODEL_DIR,
                            dataset_name=os.path.basename(str(args.real)))
        logger.info("No artifacts were modified.")
    elif args.compare:
        if not args.real:
            parser.error("--compare requires --real [path].")
        compare_models(args.real, n_per_class=args.n_per_class)
        logger.info("No artifacts were modified.")
    elif args.real:
        dataset = _load_real_or_die(args.real)
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info("TRAINING MODE: real dataset (%s)", args.real)
        train(dataset, source="real",
              dataset_name=os.path.basename(str(args.real)))
        logger.info("Done. artifacts/: classifier.pkl, tfidf.pkl, meta.pkl "
                    "(source=real)")
    else:
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info("TRAINING MODE: synthetic (no --real dataset provided). "
                    "The committed artifacts are synthetic-trained unless you "
                    "pass --real [path]. Default real path: %s",
                    _REAL_DATASET_PATH)
        df = build_synthetic_dataset(n_per_class=args.n_per_class)
        logger.info("Generated %d balanced synthetic samples.", len(df))
        train(df, source="synthetic", dataset_name="synthetic-generator")
        logger.info("Done. artifacts/: classifier.pkl, tfidf.pkl, meta.pkl "
                    "(source=synthetic)")
