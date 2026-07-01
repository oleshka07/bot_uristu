"""Pytest configuration and shared fixtures.

Located at the repo root so `import app` resolves. Sets a throwaway SQLite
database and disables auth before the app is imported.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_networking.db"
os.environ.setdefault("APP_PASSWORD", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_schema():
    from app.core.database import Base, engine
    from app.core import registry  # noqa: F401  (registers every ORM model)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    _reset_schema()
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    _reset_schema()
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
