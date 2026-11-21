"""A small client for the REDCap API.

REDCap has one API endpoint per server. Every request is an HTTPS POST with
the project's API token and a ``content`` parameter naming what to export
(``metadata``, ``record``, ``log`` ...). The token identifies both the user and
the project, so it is a secret: it never appears in errors, logs or repr().

REDCap API docs: on your REDCap server, under "API" -> "API Documentation".
"""

from collections.abc import Iterator, Sequence
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from janice_pipeline.synthetic.dictionary import Field, fields_from_rows

DEFAULT_TIMEOUT_SECONDS = 120.0

DEFAULT_BATCH_SIZE = 500

# REDCap reads dateRangeBegin in its server's local time. The KWTRP server
# runs on UTC (Control Center, 21 Nov 2026); other servers may differ.
DEFAULT_SERVER_TIMEZONE = "UTC"

# Export codes, not labels ("1", not "Alive"), in one row per record or repeat
# instance. Labels can be edited in REDCap at any time; codes are stable.
RAW_FLAT = {"type": "flat", "rawOrLabel": "raw", "rawOrLabelHeaders": "raw"}


class RedcapError(Exception):
    """REDCap refused or failed a request. The message never contains the token."""


class RedcapClient:
    """Client for one REDCap project (one API token)."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        server_timezone: str = DEFAULT_SERVER_TIMEZONE,
        transport: httpx.BaseTransport | None = None,
    ):
        if urlparse(url).scheme != "https":
            raise ValueError("REDCap API URL must use https, so the token is never sent in clear")
        self.url = url
        self._token = token
        self.server_timezone = ZoneInfo(server_timezone)
        # transport is only passed in tests, to replace the network with a fake server
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return f"RedcapClient(url={self.url!r}, token=<hidden>)"

    def export_metadata(self) -> list[Field]:
        """The project's data dictionary, as fields in order."""
        return fields_from_rows(self._post({"content": "metadata"}))

    def export_record_ids(
        self, record_id_field: str, *, changed_since: datetime | None = None
    ) -> list[str]:
        """Record IDs in REDCap's order, each once.

        All records, or with ``changed_since`` only those created or changed
        after that moment. It must carry a time zone, so it means one moment
        wherever the pipeline runs.
        """
        params = {"content": "record", **RAW_FLAT, **_as_list("fields", [record_id_field])}
        if changed_since is not None:
            params["dateRangeBegin"] = self._server_time(changed_since)
        rows = self._post(params)
        # dict.fromkeys drops repeats (a record with repeating instruments comes
        # back once per instance) and, unlike set(), keeps the order
        return list(dict.fromkeys(row[record_id_field] for row in rows))

    def export_records(
        self, record_ids: Sequence[str], *, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> Iterator[list[dict[str, str]]]:
        """The records with these IDs, as one list of rows per batch of IDs.

        Returns a generator: each batch is requested only when the caller asks for it,
        so only one batch is in memory at a time, however large the project.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        return self._record_batches(record_ids, batch_size)

    def _record_batches(
        self, record_ids: Sequence[str], batch_size: int
    ) -> Iterator[list[dict[str, str]]]:
        for start in range(0, len(record_ids), batch_size):
            batch = record_ids[start : start + batch_size]
            yield self._post(
                {
                    "content": "record",
                    **RAW_FLAT,
                    "exportCheckboxLabel": "false",
                    **_as_list("records", batch),
                }
            )

    def _post(self, params: dict[str, str]) -> list[dict[str, str]]:
        data = {"token": self._token, "format": "json", "returnFormat": "json", **params}
        try:
            response = self._http.post(self.url, data=data)
        except httpx.HTTPError as error:
            raise RedcapError(f"Could not reach REDCap at {self.url}: {error}") from None

        if response.status_code != 200:
            raise RedcapError(
                f"REDCap returned HTTP {response.status_code}: {_error_message(response)}"
            )
        try:
            return response.json()
        except ValueError:
            raise RedcapError("REDCap response was not valid JSON") from None

    def _server_time(self, moment: datetime) -> str:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("changed_since needs a time zone, e.g. datetime.now(UTC)")
        return moment.astimezone(self.server_timezone).strftime("%Y-%m-%d %H:%M:%S")


def _as_list(name: str, values: Sequence[str]) -> dict[str, str]:
    """A list in the form REDCap (PHP) reads: name[0]=a, name[1]=b ..."""
    return {f"{name}[{i}]": value for i, value in enumerate(values)}


def _error_message(response: httpx.Response) -> str:
    """REDCap's own error text when it sends {"error": ...}, else the start of the body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and "error" in body:
        return str(body["error"])
    return response.text[:200]
