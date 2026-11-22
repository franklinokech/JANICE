"""Tests for the Dagster definitions: what Dagster loads, and that assets run.

Dagster docs: https://docs.dagster.io
"""

import csv

import dagster as dg
import pytest

from janice_pipeline.definitions import build_defs, defs, source_from_env
from janice_pipeline.orchestration.staging import RedcapSourceResource, SyntheticSourceResource
from janice_pipeline.orchestration.synthetic import SyntheticExportConfig, synthetic_redcap_export


def test_definitions_load_without_errors():
    # The same check Dagster runs when the UI or daemon loads the code
    dg.Definitions.validate_loadable(defs)


def test_synthetic_export_asset_is_registered():
    asset_keys = {key.to_user_string() for key in defs.resolve_all_asset_keys()}

    assert "synthetic_redcap_export" in asset_keys


def test_synthetic_export_asset_writes_records_and_reports_metadata(small_dictionary, tmp_path):
    out = tmp_path / "synthetic.csv"
    config = SyntheticExportConfig(
        dictionary_path=str(small_dictionary), output_path=str(out), records=12, seed=1
    )

    result = dg.materialize(
        [synthetic_redcap_export],
        run_config=dg.RunConfig({"synthetic_redcap_export": config}),
    )

    assert result.success
    with out.open(newline="") as f:
        assert len(list(csv.DictReader(f))) == 12

    (materialization,) = result.asset_materializations_for_node("synthetic_redcap_export")
    assert materialization.metadata["records"].value == 12


def test_staging_asset_is_registered():
    asset_keys = {key.to_user_string() for key in defs.resolve_all_asset_keys()}

    assert "redcap_staging" in asset_keys


def test_records_are_synthetic_unless_redcap_is_asked_for_explicitly():
    # Safe default: a laptop with no settings can never pull real data
    assert isinstance(source_from_env({}), SyntheticSourceResource)


def test_redcap_source_is_used_when_asked_for():
    env = {"JANICE_SOURCE": "redcap", "REDCAP_API_URL": "https://redcap.example.org/api/"}

    source = source_from_env(env)

    assert isinstance(source, RedcapSourceResource)
    assert source.default_api_url == "https://redcap.example.org/api/"


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError, match="JANICE_SOURCE"):
        source_from_env({"JANICE_SOURCE": "production"})


def test_data_files_live_outside_the_repository_by_default(tmp_path):
    defs_for_test = build_defs({"JANICE_DATA_DIR": str(tmp_path)})

    staging = defs_for_test.resources["staging"]
    assert staging.db_path("neonatal") == tmp_path / "staging_neonatal.duckdb"


def test_partitions_come_from_the_project_registry(tmp_path):
    registry = tmp_path / "projects.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: neonatal\n    site_field: hosp_id\n"
        "  - key: kilifi_nbu\n    site_field: facility_code\n"
    )

    defs_for_test = build_defs({"JANICE_PROJECTS_FILE": str(registry)})

    asset = defs_for_test.resolve_assets_def("redcap_staging")
    assert asset.partitions_def.get_partition_keys() == ["neonatal", "kilifi_nbu"]


def test_warehouse_asset_and_ingest_job_are_registered():
    asset_keys = {key.to_user_string() for key in defs.resolve_all_asset_keys()}

    assert "warehouse_raw" in asset_keys
    assert defs.resolve_job_def("ingest_project") is not None
