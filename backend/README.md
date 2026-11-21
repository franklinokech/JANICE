# JANICE backend

Django + Django REST Framework API.

## Run locally

Postgres runs in Docker; Django reads its settings from the repository-root `.env`.

```bash
cp ../.env.example ../.env       # once; then set POSTGRES_PASSWORD
docker compose up -d db          # from the repository root
uv sync
uv run --env-file ../.env python manage.py migrate
uv run --env-file ../.env python manage.py runserver
```

## Test

Tests need Postgres running (`docker compose up -d db`).

```bash
uv run --env-file ../.env pytest
```

## Settings

| Module | Used by | Secrets |
| --- | --- | --- |
| `janice.settings.dev` | `manage.py` on a laptop | Hard-coded, dev only |
| `janice.settings.test` | pytest | Hard-coded, test only |
| `janice.settings.prod` | `asgi.py` / `wsgi.py` on servers | From environment variables |


## Run in Docker

From the repository root, with `.env` filled in (see `.env.example`):

```bash
docker compose up -d --build     # db, migrations, then the API on port 8000
docker compose ps                # backend should become "healthy"
docker compose logs -f backend   # follow the API logs
docker compose down              # stop (data is kept in the pgdata volume)
```

The image runs uvicorn as a non-root user with `janice.settings.prod`,
so `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and `POSTGRES_PASSWORD` must be set.
