"""Settings used by pytest."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "django-insecure-test-only-not-a-secret"  # noqa: S105
ALLOWED_HOSTS = ["testserver"]

# Fast password hashing keeps tests quick; never use outside tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
