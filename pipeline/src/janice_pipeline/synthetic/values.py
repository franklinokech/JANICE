"""Generate synthetic values for REDCap fields.

Values follow REDCap's own export formats, so synthetic records look exactly
like a real export to the rest of the pipeline. Nothing here is random in the
security sense: a seeded generator makes every run reproducible.
"""

import random
from datetime import date, datetime, timedelta

from .dictionary import Field

# Used when a date field has no validation limits
DEFAULT_START = date(2024, 1, 1)
DEFAULT_END = date(2026, 10, 31)

# Field types REDCap computes or that hold no data in an export
NO_DATA_FIELD_TYPES = {"calc", "descriptive", "file", "sql"}

DECIMAL_PLACES = {"number": 1, "number_1dp": 1, "number_2dp": 2, "number_3dp": 3, "number_4dp": 4}


def generate_values(
    field: Field, rng: random.Random, record_number: int, *, missing_rate: float = 0.0
) -> dict[str, str]:
    """Return {column: value} for one field of one record.

    Most fields give one column. Checkboxes give one column per option
    (``name___code``), as in a REDCap export. Optional fields are left blank
    with probability ``missing_rate``, to mimic incomplete paper records.
    """
    if field.field_type in NO_DATA_FIELD_TYPES:
        return {}

    if field.field_type == "checkbox":
        return {f"{field.name}___{c.code.lower()}": rng.choice(("0", "1")) for c in field.choices}

    if not field.required and rng.random() < missing_rate:
        return {field.name: ""}

    return {field.name: _single_value(field, rng, record_number)}


def _single_value(field: Field, rng: random.Random, record_number: int) -> str:
    if field.identifier:
        return f"SYNTHETIC-{record_number:06d}"

    match field.field_type:
        case "dropdown" | "radio":
            return rng.choice(field.choices).code
        case "yesno" | "truefalse":
            return rng.choice(("0", "1"))
        case "slider":
            return str(rng.randint(0, 100))
        case "notes":
            return "Synthetic note."
        case _:
            return _text_value(field, rng, record_number)


def _text_value(field: Field, rng: random.Random, record_number: int) -> str:
    validation = field.validation

    if validation == "integer":
        low, high = _limits(_int(field.minimum), _int(field.maximum), 0, 100, 100)
        return str(rng.randint(low, high))

    if validation in DECIMAL_PLACES:
        low, high = _limits(_float(field.minimum), _float(field.maximum), 0.0, 100.0, 100.0)
        places = DECIMAL_PLACES[validation]
        value = round(rng.uniform(low, high), places)
        return f"{min(max(value, low), high):.{places}f}"

    if validation == "date_ymd":
        return _random_date(field, rng).isoformat()

    if validation in ("datetime_ymd", "datetime_seconds_ymd"):
        moment = datetime.combine(_random_date(field, rng), datetime.min.time()) + timedelta(
            seconds=rng.randint(0, 86_399)
        )
        fmt = "%Y-%m-%d %H:%M:%S" if validation == "datetime_seconds_ymd" else "%Y-%m-%d %H:%M"
        return moment.strftime(fmt)

    if validation == "time":
        return f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}"

    if validation == "email":
        return f"synthetic{record_number}@example.org"

    if validation == "phone":
        return "0000000000"

    return f"synthetic {field.name} {record_number}"


def _random_date(field: Field, rng: random.Random) -> date:
    start, end = _limits(
        _date(field.minimum), _date(field.maximum), DEFAULT_START, DEFAULT_END, timedelta(days=365)
    )
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _limits(low, high, default_low, default_high, width):
    """The range to draw from, given the limits REDCap sets (None when not set).

    A missing limit comes from the default range, unless that would put it on
    the wrong side of the limit that is set (e.g. a minimum of 1975 with the
    default maximum of 100); then it is ``width`` beyond that limit instead.
    """
    if low is not None and high is not None:
        return min(low, high), max(low, high)
    if low is not None:
        return low, max(default_high, low + width)
    if high is not None:
        return min(default_low, high - width), high
    return default_low, default_high


# REDCap also allows limits it works out itself, such as "today", "now" or a
# piped [field]; anything that isn't a plain value counts as "not set"


def _int(raw: str) -> int | None:
    return int(raw) if raw.lstrip("-").isdigit() else None


def _float(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def _date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
