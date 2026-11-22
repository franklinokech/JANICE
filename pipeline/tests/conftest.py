"""Shared fixtures: a small data dictionary, and a real Postgres for warehouse tests.

Warehouse tests get a real Postgres with their own empty schema. Connection
settings come from the same POSTGRES_* variables as the backend. Locally, start
the database with `docker compose up -d db` and run the tests with
`uv run --env-file ../.env pytest`. Without a reachable Postgres those tests are
skipped, except in CI, where JANICE_REQUIRE_POSTGRES=1 makes that a failure so
they can never be skipped by accident.
"""

import csv
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from janice_pipeline.warehouse.postgres_load import PostgresSettings

HEADERS = ["field_name", "form_name", "field_type", "select_choices_or_calculations", "identifier"]


@pytest.fixture
def small_dictionary(tmp_path):
    """A two-form data dictionary in API metadata format, written to a temporary file."""
    path = tmp_path / "dictionary.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(
            [
                ["record_id", "admission", "text", "", ""],
                ["ip_number", "admission", "text", "", "y"],
                ["danger_signs", "admission", "checkbox", "1, Convulsions | 2, Coma", ""],
                ["outcome", "discharge", "radio", "1, Alive | 2, Died", ""],
            ]
        )
    return path


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
