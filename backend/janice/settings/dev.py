"""Settings for local development on a laptop. Never use in staging or production."""

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = "django-insecure-dev-only-not-a-secret"  # noqa: S105
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
