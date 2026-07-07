"""Shared test fixtures — isolated DB per test session."""

import os
import tempfile

import pytest

# Set data dir BEFORE importing app modules
_tmpdir = tempfile.mkdtemp(prefix="kanban_test_")
os.environ["KANBAN_DATA_DIR"] = _tmpdir
os.environ["FEISHU_WEBHOOK_URL"] = ""  # disable notifications

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from db import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Create schema once per test session."""
    init_db()
    yield
    # Cleanup handled by OS temp dir lifecycle


@pytest.fixture()
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture(scope="session")
def _seed_users():
    """Register test users once per session."""
    from db import get_db
    import uuid
    with get_db() as conn:
        for name, role in [("test-human", "human"), ("test-bot", "bot"), ("feishu-bot", "bot")]:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, name, display_name, role) VALUES (?, ?, ?, ?)",
                (uuid.uuid4().hex[:8], name, name, role)
            )


@pytest.fixture()
def human_headers(_seed_users):
    """Headers for a human user."""
    return {"X-Kanban-User": "test-human", "Content-Type": "application/json"}


@pytest.fixture()
def bot_headers(_seed_users):
    """Headers for a bot user."""
    return {"X-Kanban-User": "test-bot", "Content-Type": "application/json"}
