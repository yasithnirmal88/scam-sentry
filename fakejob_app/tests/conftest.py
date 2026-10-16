"""Shared fixtures.

The ``db`` fixture runs the storage tests against the SQLite backend and,
when ``TEST_POSTGRES_URL`` is set, the same assertions against a real Postgres
backend (test container or external DB).
"""

import os

# Tests must be deterministic regardless of a developer's local .env, so force
# config to read only the real environment before it is imported below.
os.environ.setdefault("SCAM_SENTRY_NO_DOTENV", "1")

import pytest

from models.storage import PostgresBackend

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "").strip()
BACKENDS = ["sqlite"] + (["postgres"] if POSTGRES_URL else [])


@pytest.fixture(params=BACKENDS)
def db(request, tmp_path):
    """A fresh, isolated database locator for one storage test.

    SQLite -> a unique temp file. Postgres -> a ``postgres://`` URL with the
    schema dropped/recreated so each test starts clean.
    """
    if request.param == "sqlite":
        yield str(tmp_path / "test.db")
    else:
        PostgresBackend(POSTGRES_URL).reset()
        yield POSTGRES_URL
        PostgresBackend(POSTGRES_URL).reset()