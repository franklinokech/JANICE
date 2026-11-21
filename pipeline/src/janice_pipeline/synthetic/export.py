"""Write a synthetic REDCap export to a CSV file. Shared by the CLI and Dagster."""

import csv
from pathlib import Path

from .dictionary import read_data_dictionary
from .records import generate_records


def write_synthetic_export(
    dictionary_path: Path,
    output_path: Path,
    *,
    records: int,
    seed: int,
    missing_rate: float = 0.05,
) -> tuple[int, int]:
    """Generate records from a data dictionary and write them as CSV.

    Returns (number of records, number of columns).
    """
    fields = read_data_dictionary(dictionary_path)
    columns, rows = generate_records(fields, count=records, seed=seed, missing_rate=missing_rate)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), len(columns)
