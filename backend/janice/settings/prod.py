"""Settings for staging and production. Every secret comes from the environment."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403


def require_env(name: str) -> str:
    """Return an environment variable, or stop Django from starting without it."""
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Environment variable {name} must be set")
    return value


DEBUG = False
SECRET_KEY = require_env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = require_env("DJANGO_ALLOWED_HOSTS").split(",")

# HTTPS hardening (TLS is terminated by nginx in front of Django)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
