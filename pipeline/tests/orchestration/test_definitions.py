"""Tests for the Dagster definitions: what Dagster loads, and that assets run.

Dagster docs: https://docs.dagster.io
"""

import csv

import dagster as dg

from janice_pipeline.definitions import defs
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
