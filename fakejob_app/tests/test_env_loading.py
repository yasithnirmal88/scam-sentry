"""Optional ``.env`` auto-loading (config._load_env_file).

The loader is best-effort: it must never crash when the file or python-dotenv
is absent, and it must never override values already present in the real
environment. The test suite itself disables auto-loading via
``SCAM_SENTRY_NO_DOTENV`` (see ``tests/conftest.py``) so results are independent
of a developer's local ``.env``.
"""

import os

import pytest

import config

MARKER = "SCAM_SENTRY_TEST_MARKER"


def test_suite_is_isolated_from_local_env_file():
    """conftest forces pure-env config so a dev .env cannot skew other tests."""
    assert os.environ.get("SCAM_SENTRY_NO_DOTENV") == "1"


def test_missing_file_is_a_silent_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(MARKER, raising=False)
    assert config._load_env_file(str(tmp_path / "does-not-exist.env")) is False
    assert MARKER not in os.environ


def test_loads_values_from_file(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    monkeypatch.delenv(MARKER, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{MARKER}=from-dotenv\n", encoding="utf-8")
    assert config._load_env_file(str(env)) is True
    assert os.environ[MARKER] == "from-dotenv"


def test_does_not_override_existing_environment(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    monkeypatch.setenv(MARKER, "from-real-env")
    env = tmp_path / ".env"
    env.write_text(f"{MARKER}=from-dotenv\n", encoding="utf-8")
    config._load_env_file(str(env))
    assert os.environ[MARKER] == "from-real-env"
