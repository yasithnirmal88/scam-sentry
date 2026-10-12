"""Phase 5 (ML honesty): calibrated, honestly labelled ML signal.

Covers: model provenance metadata, probability calibration math, honesty
fields in the analyze response, hybrid-score formula consistency, and the
config switch that restores the raw model output.
"""

import config
from models.job import init_db


LEGIT = ("Senior Full-Stack Software Engineer at Acme Corp, Remote. Build "
         "microservices and mentor juniors. Requirements: 4+ years Python. "
         "Benefits: medical insurance and bonus. Apply via our careers portal.")

SCAM = ("Applicants must pay a refundable registration fee of $50 upfront. "
        "Send your bank account number and national ID to secure your slot. "
        "Limited positions - apply within 24 hours! Contact quickjobs99@gmail.com.")


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "ml.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    return app_module.app.test_client()


def test_model_provenance_metadata():
    from model_training import load_model_metadata
    meta = load_model_metadata()
    assert meta["available"] is True
    assert meta["source"] == "synthetic"
    assert "GradientBoosting" in meta["estimator"]
    assert meta["n_samples"] > 0
    assert meta["n_features"] > 0
    assert 0 < meta["validation_accuracy"] <= 1
    assert meta["trained_at_utc"]


def test_calibration_config_defaults():
    assert config.ML_CALIBRATION is True
    assert 0 < config.ML_CALIBRATION_PRIOR < 1
    assert 0 < config.ML_CALIBRATION_SHRINK < 1


def test_calibration_pulls_toward_prior():
    import app as app_module
    result = app_module.classify(SCAM)
    raw = result["ml_raw_probability"]
    cal = result["ml_probability"]
    prior = config.ML_CALIBRATION_PRIOR * 100
    shrink = config.ML_CALIBRATION_SHRINK
    assert abs((cal - prior) - (raw - prior) * shrink) <= 0.3
    if raw > prior:
        assert prior < cal < raw
    elif raw < prior:
        assert raw < cal < prior


def test_calibration_bounds_extremes():
    import app as app_module
    result = app_module.classify(SCAM)
    assert 0 <= result["ml_probability"] <= 95  # never a "100%" from synthetic GBC
    assert 0 <= result["ml_raw_probability"] <= 100


def test_analyze_returns_honesty_fields(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as c:
        res = c.post("/api/analyze/text", json={"text": LEGIT})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ml_note"]
    assert "supporting signal" in body["ml_note"]
    assert body["calibration"]["applied"] is True
    assert "validation accuracy" in body["ml_note"]
    assert "ml_raw_probability" in body


def test_ml_note_passes_language_discipline():
    from risk.language import check_language
    import app as app_module
    assert check_language(app_module._ml_note()) == []


def test_hybrid_uses_calibrated_ml():
    import app as app_module
    result = app_module.classify(SCAM)
    expected = round(config.RULE_WEIGHT * result["rule_score"]
                     + config.ML_WEIGHT * result["ml_score"], 3)
    assert abs(result["hybrid_score"] - expected) <= 0.002


def test_calibration_off_restores_raw(monkeypatch):
    import app as app_module
    monkeypatch.setattr(config, "ML_CALIBRATION", False)
    result = app_module.classify(SCAM)
    assert result["calibration"]["applied"] is False
    assert abs(result["ml_probability"] - result["ml_raw_probability"]) < 0.01


def test_health_reports_model_provenance(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as c:
        model = c.get("/api/health").get_json()["model"]
    assert model["available"] is True
    assert model["source"] == "synthetic"
    assert model["n_samples"] > 0
    assert model["validation_accuracy"] is not None


def test_meta_records_runtime_sklearn_version():
    import sklearn
    from model_training import load_model_metadata
    meta = load_model_metadata()
    assert meta["sklearn_version"] == sklearn.__version__


def test_meta_reports_holdout_metrics_and_honesty_note():
    from model_training import load_model_metadata
    meta = load_model_metadata()
    metrics = meta["metrics"]
    assert isinstance(metrics, dict)
    for key in ("accuracy", "precision_fake", "recall_fake", "f1_fake",
                "f1_macro", "f1_weighted", "n_train", "n_test"):
        assert key in metrics, key
    assert metrics["n_train"] + metrics["n_test"] == meta["n_samples"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    # honesty note must exist and must not overclaim real-world performance
    assert meta["honesty_note"]
    assert "not" in meta["honesty_note"].lower()


def test_health_reports_version_metrics_and_honesty_note(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as c:
        model = c.get("/api/health").get_json()["model"]
    assert model["sklearn_version"]
    assert model["metrics"]["accuracy"] is not None
    assert model["honesty_note"]


def test_synthetic_default_matches_config():
    import config
    import model_training
    assert model_training._SYNTHETIC_N_PER_CLASS == config.SYNTHETIC_SAMPLES_PER_CLASS


def test_training_pipeline_writes_artifacts_and_metadata(tmp_path):
    """The retrain path runs end-to-end into a scratch dir (no repo mutation)
    and writes a model card with metrics + provenance."""
    import os
    import pickle
    import model_training

    dataset = model_training.build_synthetic_dataset(n_per_class=12)
    model_training.train(dataset, model_dir=str(tmp_path), source="synthetic")

    for name in ("classifier.pkl", "tfidf.pkl", "meta.pkl"):
        assert os.path.exists(tmp_path / name)

    with open(tmp_path / "meta.pkl", "rb") as f:
        meta = pickle.load(f)
    assert meta["source"] == "synthetic"
    assert meta["sklearn_version"]
    assert meta["metrics"]["n_train"] + meta["metrics"]["n_test"] == meta["n_samples"]
    assert "not" in meta["honesty_note"].lower()