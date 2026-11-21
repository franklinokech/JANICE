"""A small client for the REDCap API.

REDCap has one API endpoint per server. Every request is an HTTPS POST with
the project's API token and a ``content`` parameter naming what to export
(``metadata``, ``record``, ``log`` ...). The token identifies both the user and
the project, so it is a secret: it never appears in errors, logs or repr().

REDCap API docs: on your REDCap server, under "API" -> "API Documentation".
"""

from urllib.parse import urlparse

import httpx

from janice_pipeline.synthetic.dictionary import Field, fields_from_rows

DEFAULT_TIMEOUT_SECONDS = 120.0


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
        transport: httpx.BaseTransport | None = None,
    ):
        if urlparse(url).scheme != "https":
            raise ValueError("REDCap API URL must use https, so the token is never sent in clear")
        self.url = url
        self._token = token
        # transport is only passed in tests, to replace the network with a fake server
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return f"RedcapClient(url={self.url!r}, token=<hidden>)"

    def export_metadata(self) -> list[Field]:
        """The project's data dictionary, as fields in order."""
        return fields_from_rows(self._post({"content": "metadata"}))

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


def _error_message(response: httpx.Response) -> str:
    """REDCap's own error text when it sends {"error": ...}, else the start of the body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and "error" in body:
        return str(body["error"])
    return response.text[:200]
