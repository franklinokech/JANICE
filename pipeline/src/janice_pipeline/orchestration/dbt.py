"""The dbt models as Dagster assets.

Every dbt model becomes an asset and every dbt test an asset check (via
dagster-dbt), so the whole chain shows in one Dagster graph:
REDCap -> redcap_staging -> warehouse_raw -> dbt staging -> indicators.
The dbt sources in the raw schema are mapped to warehouse_raw (in the sources
YAML), so Dagster knows the models run after the warehouse load.

Dagster reads dbt's manifest (target/manifest.json) to learn the models. It is
built with `dbt parse` when missing, which needs no database connection.
Docs: https://docs.dagster.io/integrations/libraries/dbt
"""

from pathlib import Path

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets
from dbt.cli.main import dbtRunner

DBT_PROJECT_DIR = Path(__file__).resolve().parents[3] / "dbt"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR, profiles_dir=DBT_PROJECT_DIR)


def ensure_manifest() -> Path:
    """dbt's manifest, built with `dbt parse` if it is missing."""
    if not dbt_project.manifest_path.exists():
        result = dbtRunner().invoke(
            [
                "parse",
                "--quiet",
                "--project-dir", str(DBT_PROJECT_DIR),
                "--profiles-dir", str(DBT_PROJECT_DIR),
            ]
        )  # fmt: skip
        if not result.success:
            raise RuntimeError(f"dbt parse failed: {result.exception}")
    return dbt_project.manifest_path


@dbt_assets(manifest=ensure_manifest(), project=dbt_project, name="warehouse_models")
def warehouse_models(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    """Build the dbt models and run their tests (`dbt build`)."""
    yield from dbt.cli(["build"], context=context).stream()


def dbt_resource() -> DbtCliResource:
    return DbtCliResource(project_dir=dbt_project, profiles_dir=str(DBT_PROJECT_DIR))


build_warehouse_models = dg.define_asset_job(
    name="build_warehouse_models",
    selection=dg.AssetSelection.assets(warehouse_models),
    description="Build the dbt staging models and indicators from raw.redcap_records, "
    "running every dbt test. Run after ingest_project.",
)
