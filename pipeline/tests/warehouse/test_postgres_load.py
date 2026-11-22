"""Tests for loading a project's staging table into Postgres.

Every project lands in one table, <schema>.redcap_records, one row per record
(or repeat instance) with the fields in a JSONB column. Projects can differ in
structure without any change to the warehouse; dbt picks out the fields.
"""

from pathlib import Path

import duckdb
import pytest
from psycopg import sql

from janice_pipeline.warehouse.postgres_load import PostgresSettings, load_project


def make_staging(path: Path, project: str, rows: list[dict[str, str]]) -> Path:
    """A staging file like stage_project writes: text columns, record ID first."""
    columns = list(rows[0])
    with duckdb.connect(str(path)) as con:
        con.execute(f"CREATE TABLE raw_{project} ({', '.join(f'{c} VARCHAR' for c in columns)})")
        con.executemany(
            f"INSERT INTO raw_{project} VALUES ({', '.join('?' for _ in columns)})",  # noqa: S608
            [[row[c] for c in columns] for row in rows],
        )
    return path


def fetch(conn, schema, query, *params):
    return conn.execute(sql.SQL(query).format(schema=sql.Identifier(schema)), params).fetchall()


NEONATAL = [
    {"record_id": "1", "hosp_id": "H01", "outcome": "1", "weight": "2.4"},
    {"record_id": "2", "hosp_id": "H02", "outcome": "2", "weight": ""},
]


def test_every_row_is_loaded_with_its_project_and_record_id(tmp_path, warehouse):
    settings, schema, conn = warehouse
    staging = make_staging(tmp_path / "s.duckdb", "neonatal", NEONATAL)

    result = load_project(staging, project_key="neonatal", settings=settings, schema=schema)

    assert (result.records, result.rows) == (2, 2)
    rows = fetch(
        conn, schema, "SELECT project, record_id, data FROM {schema}.redcap_records ORDER BY 2"
    )
    assert rows[0] == ("neonatal", "1", {"hosp_id": "H01", "outcome": "1", "weight": "2.4"})


def test_blank_values_are_left_out_of_the_data(tmp_path, warehouse):
    # REDCap exports a blank for "not filled in"; leaving it out keeps rows
    # small, and data->>'weight' is NULL either way
    settings, schema, conn = warehouse
    staging = make_staging(tmp_path / "s.duckdb", "neonatal", NEONATAL)

    load_project(staging, project_key="neonatal", settings=settings, schema=schema)

    (data,) = fetch(conn, schema, "SELECT data FROM {schema}.redcap_records WHERE record_id = '2'")
    assert "weight" not in data[0]


def test_repeat_instances_are_separate_rows(tmp_path, warehouse):
    settings, schema, conn = warehouse
    rows = [
        {
            "record_id": "10",
            "redcap_repeat_instrument": "",
            "redcap_repeat_instance": "",
            "hosp_id": "H01",
        },
        {
            "record_id": "10",
            "redcap_repeat_instrument": "prev_preg",
            "redcap_repeat_instance": "1",
            "hosp_id": "",
        },
        {
            "record_id": "10",
            "redcap_repeat_instrument": "prev_preg",
            "redcap_repeat_instance": "2",
            "hosp_id": "",
        },
    ]
    staging = make_staging(tmp_path / "s.duckdb", "maternity", rows)

    result = load_project(staging, project_key="maternity", settings=settings, schema=schema)

    assert (result.records, result.rows) == (1, 3)
    keys = fetch(
        conn,
        schema,
        "SELECT repeat_instrument, repeat_instance FROM {schema}.redcap_records ORDER BY 1, 2",
    )
    assert keys == [("", ""), ("prev_preg", "1"), ("prev_preg", "2")]


def test_a_reload_replaces_the_project_and_leaves_other_projects_alone(tmp_path, warehouse):
    settings, schema, conn = warehouse
    neonatal = make_staging(tmp_path / "n.duckdb", "neonatal", NEONATAL)
    paeds = make_staging(tmp_path / "p.duckdb", "paediatrics", [{"record_id": "1", "a": "x"}])
    load_project(neonatal, project_key="neonatal", settings=settings, schema=schema)
    load_project(paeds, project_key="paediatrics", settings=settings, schema=schema)

    smaller = make_staging(tmp_path / "n2.duckdb", "neonatal", NEONATAL[:1])
    load_project(smaller, project_key="neonatal", settings=settings, schema=schema)

    counts = fetch(
        conn,
        schema,
        "SELECT project, count(*) FROM {schema}.redcap_records GROUP BY 1 ORDER BY 1",
    )
    assert counts == [("neonatal", 1), ("paediatrics", 1)]


def test_a_failed_load_leaves_the_previous_load_in_place(tmp_path, warehouse):
    settings, schema, conn = warehouse
    good = make_staging(tmp_path / "good.duckdb", "neonatal", NEONATAL)
    load_project(good, project_key="neonatal", settings=settings, schema=schema)

    # The same record twice breaks the key, part-way through the load
    duplicated = make_staging(tmp_path / "bad.duckdb", "neonatal", [NEONATAL[0], NEONATAL[0]])
    with pytest.raises(Exception, match="duplicate key"):
        load_project(duplicated, project_key="neonatal", settings=settings, schema=schema)

    # All or nothing: dashboards never see half a load
    assert fetch(conn, schema, "SELECT count(*) FROM {schema}.redcap_records") == [(2,)]


def test_each_load_is_recorded(tmp_path, warehouse):
    settings, schema, conn = warehouse
    staging = make_staging(tmp_path / "s.duckdb", "neonatal", NEONATAL)

    load_project(staging, project_key="neonatal", settings=settings, schema=schema)

    assert fetch(conn, schema, "SELECT project, records, rows FROM {schema}.loads") == [
        ("neonatal", 2, 2)
    ]


def test_a_missing_staging_table_is_reported_clearly(tmp_path, warehouse):
    settings, schema, _ = warehouse
    staging = make_staging(tmp_path / "s.duckdb", "neonatal", NEONATAL)

    with pytest.raises(ValueError, match="raw_maternity"):
        load_project(staging, project_key="maternity", settings=settings, schema=schema)


@pytest.mark.parametrize("project_key", ["Neonatal", "neonatal; DROP TABLE x"])
def test_unsafe_project_keys_are_refused(tmp_path, project_key):
    settings = PostgresSettings("localhost", 5432, "janice", "janice", "x")

    with pytest.raises(ValueError, match="project key"):
        load_project(tmp_path / "s.duckdb", project_key=project_key, settings=settings)


def test_unsafe_schema_names_are_refused(tmp_path):
    settings = PostgresSettings("localhost", 5432, "janice", "janice", "x")

    with pytest.raises(ValueError, match="schema"):
        load_project(
            tmp_path / "s.duckdb", project_key="neonatal", settings=settings, schema="raw; --"
        )


def test_settings_come_from_the_backends_postgres_variables():
    env = {
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5433",
        "POSTGRES_DB": "janice",
        "POSTGRES_USER": "janice",
        "POSTGRES_PASSWORD": "not-a-real-password",  # noqa: S105
    }

    settings = PostgresSettings.from_env(env)

    assert (settings.host, settings.port, settings.dbname) == ("db", 5433, "janice")
    # The password never shows up when settings are printed or logged
    assert "not-a-real-password" not in repr(settings)


def test_a_missing_password_names_the_variable():
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        PostgresSettings.from_env({"POSTGRES_DB": "janice", "POSTGRES_USER": "janice"})
