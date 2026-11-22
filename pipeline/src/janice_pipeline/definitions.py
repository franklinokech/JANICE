"""Everything Dagster loads for the JANICE pipeline.

Start the local UI with:  uv run dg dev

Settings come from the environment (the git-ignored .env on a laptop):
- JANICE_SOURCE: "synthetic" (default, for laptops and CI) or "redcap"
  (staging and production servers only: real data).
- JANICE_DATA_DIR: where data dictionaries and the staging file live
  (default ~/janice-data, outside the repository).
- REDCAP_API_URL, REDCAP_SERVER_TIMEZONE: used when JANICE_SOURCE=redcap.
Secrets (REDCAP_TOKEN_<UNIT>, JANICE_HASH_KEY) are read only when a run starts.
"""

import os
from collections.abc import Mapping
from pathlib import Path

import dagster as dg

from janice_pipeline.orchestration.staging import (
    RecordSourceResource,
    RedcapSourceResource,
    StagingResource,
    SyntheticSourceResource,
    redcap_staging,
)
from janice_pipeline.orchestration.synthetic import synthetic_redcap_export
from janice_pipeline.redcap.client import DEFAULT_SERVER_TIMEZONE


def source_from_env(env: Mapping[str, str]) -> RecordSourceResource:
    """Synthetic records unless the environment explicitly asks for real REDCap."""
    choice = env.get("JANICE_SOURCE", "synthetic")
    if choice == "synthetic":
        return SyntheticSourceResource(dictionary_dir=str(data_dir(env)))
    if choice == "redcap":
        return RedcapSourceResource(
            api_url=env.get("REDCAP_API_URL", ""),
            server_timezone=env.get("REDCAP_SERVER_TIMEZONE", DEFAULT_SERVER_TIMEZONE),
        )
    raise ValueError(f"JANICE_SOURCE must be 'synthetic' or 'redcap', not {choice!r}")


def data_dir(env: Mapping[str, str]) -> Path:
    return Path(env.get("JANICE_DATA_DIR", Path.home() / "janice-data"))


def build_defs(env: Mapping[str, str]) -> dg.Definitions:
    return dg.Definitions(
        assets=[synthetic_redcap_export, redcap_staging],
        resources={
            "source": source_from_env(env),
            "staging": StagingResource(data_dir=str(data_dir(env))),
        },
    )


defs = build_defs(os.environ)
