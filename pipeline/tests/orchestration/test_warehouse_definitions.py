"""Tests for how warehouse_raw fits into Dagster, without a database."""

import dagster as dg

from janice_pipeline.orchestration.staging import (
    RecordSourceResource,
    StagingResource,
    build_staging_asset,
)
from janice_pipeline.orchestration.warehouse import (
    WarehouseResource,
    build_ingest_job,
    build_warehouse_asset,
)
from janice_pipeline.projects.registry import Project

PROJECTS = [
    Project(key="neonatal", site_field="hosp_id"),
    Project(key="kilifi_nbu", site_field="facility_code"),
]


def test_warehouse_raw_has_the_same_partitions_as_staging():
    staging = build_staging_asset(PROJECTS)
    raw = build_warehouse_asset(PROJECTS)

    assert raw.partitions_def.get_partition_keys() == staging.partitions_def.get_partition_keys()


def test_warehouse_raw_runs_after_staging():
    raw = build_warehouse_asset(PROJECTS)

    (dependency,) = raw.dependency_keys

    assert dependency.to_user_string() == "redcap_staging"


def test_the_ingest_job_runs_both_steps_for_one_project():
    staging = build_staging_asset(PROJECTS)
    raw = build_warehouse_asset(PROJECTS)
    defs = dg.Definitions(
        assets=[staging, raw],
        jobs=[build_ingest_job()],
        resources={
            "source": RecordSourceResource(),
            "staging": StagingResource(data_dir="/tmp"),  # noqa: S108 (never written)
            "warehouse": WarehouseResource(),
        },
    )

    job = defs.resolve_job_def("ingest_project")

    assert {node.name for node in job.nodes} == {"redcap_staging", "warehouse_raw"}
    assert job.partitions_def.get_partition_keys() == ["neonatal", "kilifi_nbu"]


def test_missing_database_settings_fail_the_load_with_the_variable_name(tmp_path, monkeypatch):
    for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "staging_neonatal.duckdb").touch()

    result = dg.materialize(
        [build_warehouse_asset(PROJECTS)],
        partition_key="neonatal",
        resources={
            "staging": StagingResource(data_dir=str(tmp_path)),
            "warehouse": WarehouseResource(),
        },
        raise_on_error=False,
    )

    assert not result.success
    assert "POSTGRES_PASSWORD" in str(result.get_step_failure_events()[0].event_specific_data)
