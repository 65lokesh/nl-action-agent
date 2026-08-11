import os

# Force mock mode for the entire test session, regardless of what's in
# .env locally. Tests must be deterministic and not depend on live API
# calls or whatever mode a developer happens to have set for manual
# testing.
os.environ["MOCK_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import store


@pytest.fixture
def client():
    store._reset()
    return TestClient(app)
