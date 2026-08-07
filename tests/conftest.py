"""Test harness: runs the whole suite against an isolated temp SQLite DB.

Important: the env var must be set before any app module is imported, because
`get_settings()` is lru_cached and `app.main` reads `settings.db_path` at
import time. conftest is imported before test modules, so it's safe here.
"""

import os
import pathlib
import tempfile

os.environ["DB_PATH"] = str(
    pathlib.Path(tempfile.mkdtemp(prefix="vidpack-test-")) / "test.db"
)

import pytest  # noqa: E402


@pytest.fixture()
def client_factory():
    """Provide a fresh TestClient per test; keeps `app` mutable for reuse."""
    from fastapi.testclient import TestClient

    return TestClient