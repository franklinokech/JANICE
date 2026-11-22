"""Dagster asset that loads each staged project into the Postgres warehouse.

``warehouse_raw`` has one partition per project, like ``redcap_staging``, and
depends on it partition by partition: loading "neonatal" uses the file that
staging "neonatal" wrote. The ``ingest_project`` job runs both for one project,
so a single launch takes a project from REDCap to raw.redcap_records.

The database password is read from the environment when the run starts, never
from Dagster's config.
"""

import os

import dagster as dg

from janice_pipeline.orchestration.staging import StagingResource, project_partitions
from janice_pipeline.projects.registry import Project
from janice_pipeline.warehouse.postgres_load import (
    DEFAULT_SCHEMA,
    PostgresSettings,
    load_project,
)

STAGING_ASSET = dg.AssetKey("redcap_staging")


class WarehouseResource(dg.ConfigurableResource):
    """The Postgres warehouse. Connection settings come from POSTGRES_* at run time."""

    schema_name: str = DEFAULT_SCHEMA

    def settings(self) -> PostgresSettings:
        try:
            return PostgresSettings.from_env(os.environ)
        except ValueError as error:
            raise dg.Failure(f"Cannot connect to the warehouse: {error}") from None


def build_warehouse_asset(projects: list[Project]) -> dg.AssetsDefinition:
    """The load asset, with one partition per project, after redcap_staging."""
    by_key = {project.key: project for project in projects}

    @dg.asset(
        name="warehouse_raw",
        partitions_def=project_partitions(projects),
        deps=[STAGING_ASSET],
        group_name="ingestion",
        description="One project's staged records loaded into raw.redcap_records "
        "(one JSONB row per record or repeat instance), replacing its previous load "
        "in one transaction.",
        kinds={"python", "postgres"},
    )
    def warehouse_raw(
        context: dg.AssetExecutionContext,
        staging: StagingResource,
        warehouse: WarehouseResource,
    ) -> dg.MaterializeResult:
        project = by_key[context.partition_key]
        project_key = project.key
        settings = warehouse.settings()
        staging_db = staging.db_path(project_key)
        if not staging_db.exists():
            raise dg.Failure(
                f"No staging file for {project_key} at {staging_db}: "
                f"materialize redcap_staging for {project_key} first"
            )

        result = load_project(
            staging_db,
            project_key=project_key,
            settings=settings,
            site_field=project.site_field,
            schema=warehouse.schema_name,
        )
        context.log.info(f"Loaded {result.rows} {project_key} rows into the warehouse")
        return dg.MaterializeResult(
            metadata={
                "table": f"{warehouse.schema_name}.redcap_records",
                "records": result.records,
                "rows": result.rows,
            }
        )

    return warehouse_raw


def build_ingest_job():
    """Stage and load one project: REDCap -> DuckDB -> Postgres.

    Dagster takes the job's partitions (one per project) from its two assets.
    """
    return dg.define_asset_job(
        name="ingest_project",
        selection=dg.AssetSelection.assets(STAGING_ASSET, "warehouse_raw"),
        description="Stage one project from REDCap (identifiers hashed) and load it into "
        "the warehouse. Pick the project as the partition.",
    )
