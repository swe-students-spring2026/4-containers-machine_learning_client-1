"""Pytest for Flask app."""

import os
import sys

import pytest
from app import app

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))




@pytest.fixture(name="client")
def fixture_client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client
