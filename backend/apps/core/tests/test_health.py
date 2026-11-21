"""Tests for the health check endpoint.

The health endpoint lets monitoring tools, Docker and CI ask "is the API up,
and can it reach its database?" without logging in. It also proves URL path
versioning (/api/v1/...) works.
"""

import pytest
from django.db import OperationalError
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_returns_ok_when_database_is_reachable():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_is_unreachable(monkeypatch):
    class BrokenConnection:
        def cursor(self):
            raise OperationalError("could not connect to server")

    monkeypatch.setattr("apps.core.views.connection", BrokenConnection())

    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


def test_health_url_can_be_reversed_by_name():
    url = reverse("health", kwargs={"version": "v1"})

    assert url == "/api/v1/health/"


def test_unsupported_api_version_returns_404():
    response = APIClient().get("/api/v2/health/")

    assert response.status_code == 404


def test_health_only_allows_get():
    response = APIClient().post("/api/v1/health/")

    assert response.status_code == 405
