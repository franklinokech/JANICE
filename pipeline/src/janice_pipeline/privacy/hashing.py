"""Replace identifier values with keyed hashes before data reaches the warehouse.

Algorithm: HMAC-SHA256(secret key, normalised value), as 64 lowercase hex
characters. A plain SHA-256 would not be enough: names, phone numbers and
inpatient numbers come from small sets of possible values, so anyone could
hash every candidate and look the result up. The secret key prevents that,
while the same value still always gives the same hash, so records can be linked.

Which fields are protected: those REDCap flags as identifiers, except an
explicit keep-in-clear list (e.g. the site field). Flagged free-text and
checkbox fields are dropped rather than hashed.
"""

import hashlib
import hmac
import re

from janice_pipeline.synthetic.dictionary import Field

MIN_KEY_BYTES = 32  # 256 bits, the output size of SHA-256

# Field types whose values are useless once hashed, so they are dropped instead
DROPPED_FIELD_TYPES = {"notes", "checkbox"}


def normalise(value: str, field: Field | None = None) -> str:
    """Make equivalent spellings identical: trim, collapse spaces, ignore case.

    Phone numbers also lose separators, so "0712 345-678" equals "0712345678".
    """
    text = " ".join(value.split()).casefold()
    if field is not None and field.validation == "phone":
        text = re.sub(r"[^0-9+]", "", text)
    return text


def hash_identifier(value: str, key: bytes, field: Field | None = None) -> str:
    """Return the HMAC-SHA256 hex digest of the normalised value; blanks stay blank."""
    if len(key) < MIN_KEY_BYTES:
        raise ValueError(f"Hashing key must be at least {MIN_KEY_BYTES} bytes")
    text = normalise(value, field)
    if not text:
        return ""
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()


def fields_to_protect(fields: list[Field], keep_in_clear: set[str] = frozenset()) -> set[str]:
    """Names of fields flagged as identifiers in REDCap, minus those kept in clear text."""
    return {f.name for f in fields if f.identifier} - set(keep_in_clear)


def protect_row(
    row: dict[str, str],
    fields: list[Field],
    key: bytes,
    keep_in_clear: set[str] = frozenset(),
) -> dict[str, str]:
    """Return a copy of a REDCap export row with identifiers hashed or dropped."""
    protected = fields_to_protect(fields, keep_in_clear)
    by_name = {f.name: f for f in fields}
    result: dict[str, str] = {}

    for column, value in row.items():
        # Checkbox columns are named <field>___<code>
        field = by_name.get(column.split("___")[0])
        if field is None or field.name not in protected:
            result[column] = value
        elif field.field_type in DROPPED_FIELD_TYPES:
            continue
        else:
            result[column] = hash_identifier(value, key, field)

    return result
