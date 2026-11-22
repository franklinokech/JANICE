"""End-to-end tests for the dbt project: load synthetic REDCap rows with the
real loader, then run `dbt build` (models, data tests and unit tests).
"""

from pathlib import Path

import duckdb
import pytest
from dbt.cli.main import dbtRunner
from psycopg import sql

from janice_pipeline.warehouse.postgres_load import load_project

DBT_PROJECT = Path(__file__).resolve().parents[2] / "dbt"


def make_staging(path: Path, project: str, rows: list[dict[str, str]]) -> Path:
    columns = list(rows[0])
    with duckdb.connect(str(path)) as con:
        con.execute(f"CREATE TABLE raw_{project} ({', '.join(f'{c} VARCHAR' for c in columns)})")
        con.executemany(
            f"INSERT INTO raw_{project} VALUES ({', '.join('?' for _ in columns)})",  # noqa: S608
            [[row[c] for c in columns] for row in rows],
        )
    return path


@pytest.fixture
def dbt_build(warehouse, tmp_path):
    """Returns a function that runs `dbt build` against the test schemas."""
    _, schema, conn = warehouse
    prefix = f"{schema}_"

    def run(*select: str):
        args = [
            "build",
            "--project-dir", str(DBT_PROJECT),
            "--profiles-dir", str(DBT_PROJECT),
            "--target-path", str(tmp_path / "dbt-target"),
            "--log-path", str(tmp_path / "dbt-logs"),
            "--vars", f"{{raw_schema: {schema}, schema_prefix: {prefix}}}",
        ]  # fmt: skip
        if select:
            args += ["--select", *select]
        return dbtRunner().invoke(args)

    yield run

    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(prefix + "stg")))
    conn.commit()


def failed(result) -> set[str]:
    """Names of the dbt nodes (models or tests) that failed or errored."""
    return {r.node.name for r in result.result if str(r.status) in ("fail", "error")}


def load(tmp_path, warehouse, project, rows, site_field="hosp_id"):
    settings, schema, _ = warehouse
    staging = make_staging(tmp_path / f"{project}.duckdb", project, rows)
    load_project(
        staging, project_key=project, settings=settings, schema=schema, site_field=site_field
    )


MATERNITY = [
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
]


def test_dbt_build_passes_on_loaded_data(tmp_path, warehouse, dbt_build):
    _, schema, conn = warehouse
    load(tmp_path, warehouse, "neonatal", [{"record_id": "1", "hosp_id": "H01"}])
    load(tmp_path, warehouse, "maternity", MATERNITY)

    result = dbt_build()

    assert result.success, failed(result) or result.exception
    rows = conn.execute(
        sql.SQL("SELECT record_key, site_id FROM {}.stg_redcap__records ORDER BY 1").format(
            sql.Identifier(f"{schema}_stg")
        )
    ).fetchall()
    assert rows == [("maternity:10", "H01"), ("maternity:10", "H01"), ("neonatal:1", "H01")]


def test_a_record_without_a_site_fails_the_build(tmp_path, warehouse, dbt_build):
    # Such a record could not be limited to the sites a user may see
    load(tmp_path, warehouse, "neonatal", [{"record_id": "1", "hosp_id": ""}])

    result = dbt_build()

    assert failed(result) == {"not_null_stg_redcap__records_site_id"}


def test_a_record_with_two_sites_fails_the_build(tmp_path, warehouse, dbt_build):
    rows = [
        {"record_id": "1", "redcap_repeat_instrument": "", "redcap_repeat_instance": "",
         "hosp_id": "H01"},
        {"record_id": "1", "redcap_repeat_instrument": "visit", "redcap_repeat_instance": "1",
         "hosp_id": "H02"},
    ]  # fmt: skip
    load(tmp_path, warehouse, "neonatal", rows)

    result = dbt_build()

    assert "assert_one_site_per_record" in failed(result)
