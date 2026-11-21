"""Shared pytest fixtures for the backend."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Start every test with an empty cache, so rate-limit counters never leak between tests."""
    cache.clear()
    yield
    cache.clear()
