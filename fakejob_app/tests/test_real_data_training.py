"""Real-dataset (EMSCAD-style) loading, training, and evaluation tests.

These use a tiny committed fixture CSV (`tests/fixtures/`) so CI never needs
the full Kaggle `fake_job_postings.csv`. They assert honest provenance:
metadata must record whether the model was trained on real or synthetic data,
and real mode must produce hold-out metrics.
"""

import os
import pickle
import subprocess
import sys

import pytest

import model_training

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(APP_DIR, "tests", "fixtures", "fake_job_postings_sample.csv")


def _meta(model_dir):
    with open(os.path.join(model_dir, "meta.pkl"), "rb") as f:
        return pickle.load(f)


def test_default_real_dataset_path_is_under_data():
    assert model_training._REAL_DATASET_PATH.replace("\\", "/").endswith(
        "data/fake_job_postings.csv")


def test_load_real_dataset_builds_text_and_labels():
    df = model_training.load_real_dataset(FIXTURE)
    assert list(df.columns) == ["text", "label"]
    # 14 valid rows; the blank-text row and the bad-label row are dropped.
    assert len(df) == 14
    assert set(df["label"].unique()) == {0, 1}
    assert int((df["label"] == 1).sum()) == 7
    # text field is joined from the recognised columns
    genuine = df[df["label"] == 0]["text"].iloc[0]
    assert "Software Engineer" in genuine
    assert "insurance" in genuine


def test_load_real_dataset_missing_file_fails_clearly():
    missing = os.path.join(APP_DIR, "data", "does_not_exist.csv")
    with pytest.raises(FileNotFoundError) as exc:
        model_training.load_real_dataset(missing)
    msg = str(exc.value)
    assert "fake_job_postings.csv" in msg
    assert "REAL_DATASET_PATH" in msg


def test_load_real_dataset_missing_columns_raises(tmp_path):
    bad = tmp_path / "not_a_job_dataset.csv"
    df = model_training.pd.DataFrame({"foo": [1, 2], "bar": ["a", "b"]})
    df.to_csv(bad, index=False)
    with pytest.raises(ValueError):
        model_training.load_real_dataset(str(bad))


def test_load_real_dataset_single_class_fails(tmp_path):
    bad = os.path.join(str(tmp_path), "one_class.csv")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("description,requirements,benefits,fraudulent\n")
        for i in range(4):
            f.write('"A genuine job description number %d.","ok","none",0\n' % i)
    with pytest.raises(ValueError):
        model_training.load_real_dataset(bad)


def test_synthetic_training_marks_source_synthetic(tmp_path):
    dataset = model_training.build_synthetic_dataset(n_per_class=12)
    model_training.train(dataset, model_dir=str(tmp_path), source="synthetic",
                         dataset_name="synthetic-generator")
    meta = _meta(str(tmp_path))
    assert meta["source"] == "synthetic"
    assert meta["dataset"] == "synthetic-generator"
    assert meta["class_distribution"]["fake"] > 0
    assert "synthetic" in meta["honesty_note"].lower()


def test_real_training_marks_source_real_and_reports_metrics(tmp_path):
    dataset = model_training.load_real_dataset(FIXTURE)
    model_training.train(dataset, model_dir=str(tmp_path), source="real",
                         dataset_name=os.path.basename(FIXTURE))
    meta = _meta(str(tmp_path))
    assert meta["source"] == "real"
    assert meta["dataset"] == os.path.basename(FIXTURE)
    assert meta["class_distribution"] == {"genuine": 7, "fake": 7}
    metrics = meta["metrics"]
    for key in ("accuracy", "precision_fake", "recall_fake", "f1_fake",
                "f1_macro", "f1_weighted", "n_train", "n_test"):
        assert key in metrics, key
    assert 0.0 <= metrics["accuracy"] <= 1.0
    # honesty note must mention real data and the Risk Engine, not overclaim
    note = meta["honesty_note"].lower()
    assert "real dataset" in note
    assert "risk engine" in note


def test_eval_only_reports_without_modifying_artifacts(tmp_path):
    dataset = model_training.load_real_dataset(FIXTURE)
    model_training.train(dataset, model_dir=str(tmp_path), source="real",
                         dataset_name=os.path.basename(FIXTURE))

    meta_path = os.path.join(str(tmp_path), "meta.pkl")
    clf_path = os.path.join(str(tmp_path), "classifier.pkl")
    with open(meta_path, "rb") as f:
        meta_before = f.read()
    with open(clf_path, "rb") as f:
        clf_before = f.read()

    metrics = model_training.evaluate_on_dataset(
        dataset, model_dir=str(tmp_path), dataset_name=os.path.basename(FIXTURE))
    assert "accuracy" in metrics and "f1_fake" in metrics

    with open(meta_path, "rb") as f:
        assert f.read() == meta_before
    with open(clf_path, "rb") as f:
        assert f.read() == clf_before


def test_cli_missing_real_dataset_fails_clearly():
    missing = os.path.join(APP_DIR, "data", "does_not_exist.csv")
    proc = subprocess.run(
        [sys.executable, "model_training.py", "--eval-only", "--real", missing],
        cwd=APP_DIR, capture_output=True, text=True)
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).replace("\\", "/")
    assert "not found" in combined.lower()
    assert "fake_job_postings.csv" in combined


def test_health_and_meta_shape_still_works():
    """Artifacts load and the health model card keeps its shape."""
    meta = model_training.load_model_metadata()
    assert "dataset" in meta
    assert "class_distribution" in meta
    # committed artifact is synthetic unless a real dataset was supplied
    assert meta["source"] in {"synthetic", "real"}
