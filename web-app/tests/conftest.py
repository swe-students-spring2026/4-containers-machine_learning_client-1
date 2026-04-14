"""Pytest fixtures for the web app."""

import os
import sys
import pytest

os.environ["MONGO_URI"] = "mongodb://localhost:27017"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app  # pylint: disable=wrong-import-position


@pytest.fixture(name="client")
def fixture_client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client
