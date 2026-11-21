"""Tests for the REDCap API client.

The client talks to REDCap's single API endpoint: every request is a POST
with the project's token and a "content" parameter saying what to export.
Tests use a fake REDCap server (httpx.MockTransport), so they never need a
network connection or a real token.
REDCap API docs: on your REDCap server, under "API" -> "API Documentation".
"""

from urllib.parse import parse_qs

import httpx
import pytest

from janice_pipeline.redcap.client import RedcapClient, RedcapError
from janice_pipeline.synthetic.dictionary import Choice

URL = "https://redcap.example.org/api/"
TOKEN = "0123456789ABCDEF0123456789ABCDEF"  # noqa: S105  # gitleaks:allow (fake test token)

METADATA = [
    {
        "field_name": "record_id",
        "form_name": "admission",
        "field_type": "text",
        "field_label": "Record ID",
        "select_choices_or_calculations": "",
        "text_validation_type_or_show_slider_number": "",
        "identifier": "",
        "required_field": "",
    },
    {
        "field_name": "in_gis_add",
        "form_name": "admission",
        "field_type": "text",
        "field_label": "Address",
        "select_choices_or_calculations": "",
        "text_validation_type_or_show_slider_number": "",
        "identifier": "y",
        "required_field": "",
    },
    {
        "field_name": "outcome",
        "form_name": "discharge",
        "field_type": "radio",
        "field_label": "Outcome",
        "select_choices_or_calculations": "1, Alive | 2, Died",
        "text_validation_type_or_show_slider_number": "",
        "identifier": "",
        "required_field": "y",
    },
]


def fake_redcap(handler):
    """A client whose requests go to `handler` instead of the network."""
    return RedcapClient(URL, TOKEN, transport=httpx.MockTransport(handler))


def form_data(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_export_metadata_posts_the_token_and_asks_for_json_metadata():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["data"] = form_data(request)
        return httpx.Response(200, json=METADATA)

    fake_redcap(handler).export_metadata()

    assert seen["method"] == "POST"
    assert seen["url"] == URL
    assert seen["data"]["token"] == TOKEN
    assert seen["data"]["content"] == "metadata"
    assert seen["data"]["format"] == "json"


def test_export_metadata_returns_fields_in_order_with_flags_and_choices():
    client = fake_redcap(lambda request: httpx.Response(200, json=METADATA))

    fields = client.export_metadata()

    assert [f.name for f in fields] == ["record_id", "in_gis_add", "outcome"]
    assert fields[1].identifier is True
    assert fields[2].required is True
    assert fields[2].choices == (Choice("1", "Alive"), Choice("2", "Died"))


def test_redcap_errors_are_raised_with_redcaps_message():
    error = {"error": "You do not have API Export privileges"}
    client = fake_redcap(lambda request: httpx.Response(403, json=error))

    with pytest.raises(RedcapError, match="API Export privileges"):
        client.export_metadata()


def test_error_messages_never_contain_the_token():
    client = fake_redcap(lambda request: httpx.Response(500, text="Internal error"))

    with pytest.raises(RedcapError) as raised:
        client.export_metadata()

    assert TOKEN not in str(raised.value)


def test_unreachable_server_is_reported_as_a_redcap_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RedcapError, match="Could not reach REDCap"):
        fake_redcap(handler).export_metadata()


def test_only_https_urls_are_accepted():
    # The token would otherwise travel in clear text over the network
    with pytest.raises(ValueError, match="https"):
        RedcapClient("http://redcap.example.org/api/", TOKEN)


def test_the_token_is_hidden_when_the_client_is_printed():
    client = RedcapClient(URL, TOKEN)

    assert TOKEN not in repr(client)
    assert TOKEN not in str(client)


def test_unexpected_json_is_reported_clearly():
    client = fake_redcap(lambda request: httpx.Response(200, content=b"<html>login</html>"))

    with pytest.raises(RedcapError, match="not valid JSON"):
        client.export_metadata()


def test_error_responses_that_are_not_an_error_object_are_still_reported():
    client = fake_redcap(lambda request: httpx.Response(400, json=["unexpected"]))

    with pytest.raises(RedcapError, match="HTTP 400"):
        client.export_metadata()
