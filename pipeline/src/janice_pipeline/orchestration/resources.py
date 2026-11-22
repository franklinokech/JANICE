"""Dagster resources shared by more than one asset."""

import os
from datetime import datetime

import dagster as dg

from janice_pipeline.warehouse.postgres_load import DEFAULT_SCHEMA, PostgresSettings, read_watermark


class WarehouseResource(dg.ConfigurableResource):
    """The Postgres warehouse. Connection settings come from POSTGRES_* at run time."""

    schema_name: str = DEFAULT_SCHEMA

    def settings(self) -> PostgresSettings:
        try:
            return PostgresSettings.from_env(os.environ)
        except ValueError as error:
            raise dg.Failure(f"Cannot connect to the warehouse: {error}") from None

    def watermark(self, project_key: str) -> datetime | None:
        """When the project's last successful load started reading REDCap, or None."""
        return read_watermark(self.settings(), project_key, schema=self.schema_name)
