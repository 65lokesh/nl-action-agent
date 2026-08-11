import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import store


@pytest.fixture
def client():
    store._reset()
    return TestClient(app)
