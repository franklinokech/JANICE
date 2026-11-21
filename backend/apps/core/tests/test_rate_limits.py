"""Tests for API rate limiting (throttling).

Rate limits stop one client from flooding the API, by accident or on purpose.
Docs: https://www.django-rest-framework.org/api-guide/throttling/
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient


def test_api_has_default_rate_limits_for_anonymous_and_signed_in_users():
    rest_framework = settings.REST_FRAMEWORK

    assert (
        "rest_framework.throttling.AnonRateThrottle" in rest_framework["DEFAULT_THROTTLE_CLASSES"]
    )
    assert (
        "rest_framework.throttling.UserRateThrottle" in rest_framework["DEFAULT_THROTTLE_CLASSES"]
    )
    assert set(rest_framework["DEFAULT_THROTTLE_RATES"]) >= {"anon", "user"}


@pytest.mark.django_db
def test_health_is_never_rate_limited():
    # Docker, monitoring and load balancers call /health/ constantly;
    # throttling it would make a healthy service look down.
    client = APIClient()

    statuses = {client.get("/api/v1/health/").status_code for _ in range(70)}

    assert statuses == {200}
