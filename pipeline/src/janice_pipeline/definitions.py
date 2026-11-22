"""Everything Dagster loads for the JANICE pipeline.

Start the local UI with:  uv run dg dev

Settings come from the environment (the git-ignored .env on a laptop):
- JANICE_SOURCE: "synthetic" (default, for laptops and CI) or "redcap"
  (staging and production servers only: real data).
- JANICE_DATA_DIR: where data dictionaries and the staging files live
  (default ~/janice-data, outside the repository).
- JANICE_PROJECTS_FILE: the project registry (default projects/projects.yaml).
- REDCAP_API_URL: default API URL for projects that do not set their own.
- POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER: the warehouse.
Secrets (each project's token, JANICE_HASH_KEY, POSTGRES_PASSWORD) are read
only when a run starts.
"""

import os
from collections.abc import Mapping
from pathlib import Path

import dagster as dg

from janice_pipeline.orchestration.staging import (
    API_URL_ENV,
    RecordSourceResource,
    RedcapSourceResource,
    StagingResource,
    SyntheticSourceResource,
    build_staging_asset,
)
from janice_pipeline.orchestration.synthetic import synthetic_redcap_export
from janice_pipeline.orchestration.warehouse import (
    WarehouseResource,
    build_ingest_job,
    build_warehouse_asset,
)
from janice_pipeline.projects.registry import REGISTRY_ENV, load_projects


def source_from_env(env: Mapping[str, str]) -> RecordSourceResource:
    """Synthetic records unless the environment explicitly asks for real REDCap."""
    choice = env.get("JANICE_SOURCE", "synthetic")
    if choice == "synthetic":
        return SyntheticSourceResource(dictionary_dir=str(data_dir(env)))
    if choice == "redcap":
        return RedcapSourceResource(default_api_url=env.get(API_URL_ENV, ""))
    raise ValueError(f"JANICE_SOURCE must be 'synthetic' or 'redcap', not {choice!r}")


def data_dir(env: Mapping[str, str]) -> Path:
    return Path(env.get("JANICE_DATA_DIR", Path.home() / "janice-data"))


def build_defs(env: Mapping[str, str]) -> dg.Definitions:
    projects = load_projects(env.get(REGISTRY_ENV) or None)
    return dg.Definitions(
        assets=[
            synthetic_redcap_export,
            build_staging_asset(projects),
            build_warehouse_asset(projects),
        ],
        jobs=[build_ingest_job()],
        resources={
            "source": source_from_env(env),
            "staging": StagingResource(data_dir=str(data_dir(env))),
            "warehouse": WarehouseResource(),
        },
    )


defs = build_defs(os.environ)
