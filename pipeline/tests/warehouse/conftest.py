"""A real Postgres for warehouse tests: each test gets its own empty schema.

Connection settings come from the same POSTGRES_* variables as the backend.
Locally, start the database with `docker compose up -d db` and run the tests
with `uv run --env-file ../.env pytest`. Without a reachable Postgres these
tests are skipped, except in CI, where JANICE_REQUIRE_POSTGRES=1 makes that
a failure so they can never be skipped by accident.
"""

import os
import uuid

import psycopg
import pytest
from psycopg import sql

from janice_pipeline.warehouse.postgres_load import PostgresSettings


@pytest.fixture
def warehouse():
    try:
        settings = PostgresSettings.from_env(os.environ)
        conn = psycopg.connect(**settings.connect_kwargs(), connect_timeout=3)
    except (ValueError, psycopg.OperationalError) as error:
        message = f"Postgres not reachable ({error}); start it with: docker compose up -d db"
        if os.environ.get("JANICE_REQUIRE_POSTGRES") == "1":
            pytest.fail(message)
        pytest.skip(message)

    schema = f"test_raw_{uuid.uuid4().hex[:8]}"
    try:
        yield settings, schema, conn
    finally:
        conn.rollback()
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()
