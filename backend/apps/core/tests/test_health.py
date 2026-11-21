"""Tests for the health check endpoint.

The health endpoint lets monitoring tools, Docker and CI ask "is the API up?"
without logging in. It is the first endpoint, so it also proves URL path
versioning (/api/v1/...) works.
"""

from django.urls import reverse
from rest_framework.test import APIClient


def test_health_returns_ok_on_v1():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_url_can_be_reversed_by_name():
    url = reverse("health", kwargs={"version": "v1"})

    assert url == "/api/v1/health/"


def test_unsupported_api_version_returns_404():
    response = APIClient().get("/api/v2/health/")

    assert response.status_code == 404


def test_health_only_allows_get():
    response = APIClient().post("/api/v1/health/")

    assert response.status_code == 405
