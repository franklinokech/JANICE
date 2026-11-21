"""Build complete synthetic REDCap records from a data dictionary.

The output has the same shape as a REDCap "flat" CSV export of a classic
project: one row per record, columns in data dictionary order, checkbox
options expanded to ``name___code``, and a ``<form>_complete`` status column
after each form.
"""

import random

from .dictionary import Field
from .values import generate_values

FORM_COMPLETE = "2"  # REDCap form status: 0 incomplete, 1 unverified, 2 complete


def generate_records(
    fields: list[Field], *, count: int, seed: int, missing_rate: float = 0.0
) -> tuple[list[str], list[dict[str, str]]]:
    """Return (columns, rows) for ``count`` synthetic records.

    The first field in the dictionary is the record ID; records are numbered from 1.
    """
    # Seeded on purpose: the same seed must reproduce the same synthetic data
    rng = random.Random(seed)  # noqa: S311
    record_id_field = fields[0].name
    rows = [_record(fields, record_id_field, n, rng, missing_rate) for n in range(1, count + 1)]
    columns = list(rows[0]) if rows else [record_id_field]
    return columns, rows


def _record(
    fields: list[Field], record_id_field: str, number: int, rng: random.Random, missing_rate: float
) -> dict[str, str]:
    row: dict[str, str] = {}
    for index, field in enumerate(fields):
        if field.name == record_id_field:
            row[field.name] = str(number)
        else:
            row.update(generate_values(field, rng, number, missing_rate=missing_rate))

        is_last_field_of_form = index == len(fields) - 1 or fields[index + 1].form != field.form
        if is_last_field_of_form:
            row[f"{field.form}_complete"] = FORM_COMPLETE
    return row
