"""Command-line tool: generate a synthetic REDCap export from a data dictionary.

Example:
    uv run janice-synthetic --dictionary neonatal_dictionary.csv \\
        --records 500 --seed 1 --out neonatal_synthetic.csv
"""

import argparse
import sys
from pathlib import Path

from .export import write_synthetic_export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="janice-synthetic",
        description="Generate synthetic REDCap records from a data dictionary. "
        "Never contains real data: identifiers are SYNTHETIC-nnnnnn.",
    )
    parser.add_argument("--dictionary", type=Path, required=True, help="Data dictionary CSV")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the records CSV")
    parser.add_argument("--records", type=int, default=100, help="Number of records (default 100)")
    parser.add_argument("--seed", type=int, default=1, help="Random seed (default 1)")
    parser.add_argument(
        "--missing-rate",
        type=float,
        default=0.05,
        help="Share of optional values left blank, 0 to 1 (default 0.05)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.dictionary.is_file():
        print(f"error: data dictionary not found: {args.dictionary}", file=sys.stderr)
        return 1

    record_count, column_count = write_synthetic_export(
        args.dictionary,
        args.out,
        records=args.records,
        seed=args.seed,
        missing_rate=args.missing_rate,
    )
    print(f"Wrote {record_count} synthetic records ({column_count} columns) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
