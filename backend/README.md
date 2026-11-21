# JANICE backend

Django + Django REST Framework API.

## Run locally

```bash
uv sync                                  # install dependencies
uv run python manage.py migrate
uv run python manage.py runserver        # http://localhost:8000/api/v1/health/
```

## Test

```bash
uv run pytest
```

## Settings

| Module | Used by | Secrets |
| --- | --- | --- |
| `janice.settings.dev` | `manage.py` on a laptop | Hard-coded, dev only |
| `janice.settings.test` | pytest | Hard-coded, test only |
| `janice.settings.prod` | `asgi.py` / `wsgi.py` on servers | From environment variables |
