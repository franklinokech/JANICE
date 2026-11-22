"""Tests for the dbt models as Dagster assets.

Every dbt model becomes a Dagster asset, and every dbt test an asset check, so
the data managers see the whole chain in one graph: REDCap -> staging ->
warehouse_raw -> dbt staging -> indicators. These tests check the wiring only;
tests/dbt runs the models themselves against Postgres.
"""

import dagster as dg

from janice_pipeline.definitions import defs
from janice_pipeline.orchestration.dbt import dbt_project, ensure_manifest, warehouse_models

# Asset keys are schema/model, as the tables are named in Postgres
DBT_MODELS = {
    "stg/stg_redcap__records",
    "stg/stg_neonatal__admissions",
    "qi/qi_neonatal_case_fatality_by_birth_weight",
    "qi/qi_neonatal_hypothermia_on_admission",
    "qi/qi_neonatal_kmc_under_2000g",
    "qi/qi_neonatal_antenatal_steroids_preterm",
    "qi/qi_neonatal_spo2_measured_on_admission",
}


def key(path: str) -> dg.AssetKey:
    return dg.AssetKey(path.split("/"))


def keys(asset_keys) -> set[str]:
    return {key.to_user_string() for key in asset_keys}


def test_every_dbt_model_is_an_asset():
    assert DBT_MODELS <= keys(defs.resolve_all_asset_keys())


def test_dbt_staging_runs_after_the_warehouse_load():
    # raw.redcap_records is what warehouse_raw writes; raw.projects is written
    # by the same load, and shows as an external table
    upstream = keys(warehouse_models.asset_deps[key("stg/stg_redcap__records")])

    assert upstream == {"warehouse_raw", "raw/projects"}


def test_indicators_are_built_on_the_neonatal_staging_model():
    upstream = keys(warehouse_models.asset_deps[key("qi/qi_neonatal_kmc_under_2000g")])

    assert upstream == {"stg/stg_neonatal__admissions"}


def test_dbt_tests_become_asset_checks():
    checked_assets = {key.asset_key.to_user_string() for key in warehouse_models.check_keys}

    assert "qi/qi_neonatal_hypothermia_on_admission" in checked_assets
    assert "stg/stg_neonatal__admissions" in checked_assets


def test_models_are_grouped_for_the_ui():
    groups = warehouse_models.group_names_by_key

    assert groups[key("stg/stg_neonatal__admissions")] == "warehouse"
    assert groups[key("qi/qi_neonatal_kmc_under_2000g")] == "indicators"


def test_a_job_builds_all_warehouse_models():
    job = defs.resolve_job_def("build_warehouse_models")

    assert job is not None


def test_the_manifest_is_prepared_without_a_database(monkeypatch, tmp_path):
    # dbt parse needs no connection, so Dagster can load anywhere (CI, a
    # laptop without .env) and builds the manifest when it is missing
    for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    dbt_project.manifest_path.unlink(missing_ok=True)

    manifest = ensure_manifest()

    assert manifest.exists()
