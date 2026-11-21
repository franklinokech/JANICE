"""Dagster asset that produces a synthetic REDCap export.

Lets the rest of the pipeline run end to end on synthetic data, on a laptop
or in CI, before it ever touches the real REDCap API.
"""

from pathlib import Path

import dagster as dg

from janice_pipeline.synthetic.export import write_synthetic_export


class SyntheticExportConfig(dg.Config):
    """Settings chosen when the asset is run (in the Dagster UI or in tests)."""

    dictionary_path: str
    output_path: str
    records: int = 500
    seed: int = 1
    missing_rate: float = 0.05


@dg.asset(
    group_name="synthetic",
    description="Synthetic REDCap flat export generated from a data dictionary. "
    "Contains no real data: identifiers are SYNTHETIC-nnnnnn.",
    kinds={"python", "csv"},
)
def synthetic_redcap_export(
    context: dg.AssetExecutionContext, config: SyntheticExportConfig
) -> dg.MaterializeResult:
    record_count, column_count = write_synthetic_export(
        Path(config.dictionary_path),
        Path(config.output_path),
        records=config.records,
        seed=config.seed,
        missing_rate=config.missing_rate,
    )
    context.log.info(f"Wrote {record_count} synthetic records to {config.output_path}")
    return dg.MaterializeResult(
        metadata={
            "records": record_count,
            "columns": column_count,
            "seed": config.seed,
            "path": dg.MetadataValue.path(config.output_path),
        }
    )
