"""Everything Dagster loads for the JANICE pipeline.

Start the local UI with:  uv run dg dev
"""

import dagster as dg

from janice_pipeline.orchestration.synthetic import synthetic_redcap_export

defs = dg.Definitions(assets=[synthetic_redcap_export])
