"""Tests for the Dagster asset that loads a staged project into Postgres.

``warehouse_raw`` has the same partitions as ``redcap_staging`` and depends on
it, so one run of the ``ingest_project`` job takes a project from REDCap to
raw.redcap_records. These tests use the real Postgres from conftest.py and a
fake REDCap source with synthetic records.
"""

import dagster as dg
from psycopg import sql

from janice_pipeline.orchestration.staging import (
    RecordSourceResource,
    StagingResource,
    build_staging_asset,
)
from janice_pipeline.orchestration.warehouse import (
    WarehouseResource,
    build_warehouse_asset,
)
from janice_pipeline.projects.registry import Project
from janice_pipeline.synthetic.dictionary import fields_from_rows
from janice_pipeline.synthetic.records import generate_records

FAKE_KEY_HEX = "ab" * 32  # a fake 32-byte key, for tests only
PROJECTS = [
    Project(key="neonatal", site_field="hosp_id"),
    Project(key="paediatrics", site_field="hosp_id"),
]
FIELDS = fields_from_rows(
    [
        {"field_name": "record_id", "form_name": "admission", "field_type": "text"},
        {"field_name": "hosp_id", "form_name": "admission", "field_type": "text"},
        {
            "field_name": "ip_number",
            "form_name": "admission",
            "field_type": "text",
            "identifier": "y",
        },
    ]
)


class FakeSource:
    def __init__(self, count):
        _, self.rows = generate_records(FIELDS, count=count, seed=1)

    def export_metadata(self):
        return FIELDS

    def export_record_ids(self, record_id_field):
        return [row[record_id_field] for row in self.rows]

    def export_records(self, record_ids, *, batch_size):
        for start in range(0, len(self.rows), batch_size):
            yield self.rows[start : start + batch_size]


class FakeSourceResource(RecordSourceResource):
    count: int = 6

    def for_project(self, project):
        return FakeSource(self.count)


def run(assets, tmp_path, schema="raw", project="neonatal"):
    return dg.materialize(
        assets,
        partition_key=project,
        resources={
            "source": FakeSourceResource(),
            "staging": StagingResource(data_dir=str(tmp_path)),
            "warehouse": WarehouseResource(schema_name=schema),
        },
        raise_on_error=False,
    )


def test_staging_then_loading_puts_the_project_in_postgres(tmp_path, warehouse, monkeypatch):
    _, schema, conn = warehouse
    monkeypatch.setenv("JANICE_HASH_KEY", FAKE_KEY_HEX)
    staging = build_staging_asset(PROJECTS)
    raw = build_warehouse_asset(PROJECTS)

    result = run([staging, raw], tmp_path, schema=schema, project="paediatrics")

    assert result.success
    (m,) = result.asset_materializations_for_node("warehouse_raw")
    assert m.metadata["records"].value == 6
    assert m.metadata["table"].value == f"{schema}.redcap_records"
    count = conn.execute(
        sql.SQL("SELECT count(*) FROM {}.redcap_records WHERE project = 'paediatrics'").format(
            sql.Identifier(schema)
        )
    ).fetchone()
    assert count == (6,)


def test_loading_before_staging_says_to_stage_first(tmp_path, warehouse):
    _, schema, _ = warehouse

    result = run([build_warehouse_asset(PROJECTS)], tmp_path, schema=schema)

    assert not result.success
    message = str(result.get_step_failure_events()[0].event_specific_data)
    assert "redcap_staging" in message
