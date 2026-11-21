"""Tests for the REDCap API client.

The client talks to REDCap's single API endpoint: every request is a POST
with the project's token and a "content" parameter saying what to export.
Tests use a fake REDCap server (httpx.MockTransport), so they never need a
network connection or a real token.
REDCap API docs: on your REDCap server, under "API" -> "API Documentation".
"""

from datetime import UTC, datetime
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

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


# --- Record export ---------------------------------------------------------
# Records are exported in two steps, so a large project never has to fit in
# one request or in memory: first the record IDs alone, then the records a
# batch of IDs at a time.


def test_export_record_ids_asks_only_for_the_record_id_field_in_raw_flat_form():
    seen = {}

    def handler(request):
        seen.update(form_data(request))
        return httpx.Response(200, json=[{"record_id": "1"}])

    fake_redcap(handler).export_record_ids("record_id")

    assert seen["content"] == "record"
    assert seen["type"] == "flat"
    assert seen["rawOrLabel"] == "raw"
    # PHP (REDCap) only reads lists sent as name[0], name[1] ...
    assert seen["fields[0]"] == "record_id"


def test_export_record_ids_keeps_redcap_order_and_drops_repeat_rows():
    # A record with repeating instruments (maternity's previous pregnancies)
    # comes back once per repeat instance, so its ID appears more than once
    rows = [
        {"record_id": "10", "redcap_repeat_instrument": "", "redcap_repeat_instance": ""},
        {"record_id": "10", "redcap_repeat_instrument": "prev_preg", "redcap_repeat_instance": "1"},
        {"record_id": "10", "redcap_repeat_instrument": "prev_preg", "redcap_repeat_instance": "2"},
        {"record_id": "2", "redcap_repeat_instrument": "", "redcap_repeat_instance": ""},
    ]
    client = fake_redcap(lambda request: httpx.Response(200, json=rows))

    assert client.export_record_ids("record_id") == ["10", "2"]


def test_export_records_sends_each_batch_of_ids_as_a_list():
    requests = []

    def handler(request):
        data = form_data(request)
        requests.append(data)
        ids = [v for k, v in sorted(data.items()) if k.startswith("records[")]
        return httpx.Response(200, json=[{"record_id": i} for i in ids])

    batches = list(fake_redcap(handler).export_records(["1", "2", "3", "4", "5"], batch_size=2))

    assert [[r["record_id"] for r in b] for b in batches] == [["1", "2"], ["3", "4"], ["5"]]
    assert len(requests) == 3
    assert requests[0]["records[0]"] == "1"
    assert requests[0]["records[1]"] == "2"
    assert requests[0]["content"] == "record"
    assert requests[0]["rawOrLabel"] == "raw"
    assert requests[0]["exportCheckboxLabel"] == "false"


def test_export_records_fetches_one_batch_at_a_time():
    # A generator: the next batch is only requested once the caller asks for it,
    # so only one batch is ever held in memory
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=[])

    batches = fake_redcap(handler).export_records(["1", "2", "3"], batch_size=1)
    assert calls == []
    next(batches)
    assert len(calls) == 1


def test_export_records_with_no_ids_makes_no_requests():
    def handler(request):
        raise AssertionError("no request expected")

    assert list(fake_redcap(handler).export_records([], batch_size=100)) == []


def test_batch_size_must_be_at_least_one():
    client = fake_redcap(lambda request: httpx.Response(200, json=[]))

    # Checked straight away, not on the first batch, so the mistake shows up
    # where it was made
    with pytest.raises(ValueError, match="batch_size"):
        client.export_records(["1"], batch_size=0)


def test_a_failed_batch_stops_the_export_with_a_redcap_error():
    def handler(request):
        if form_data(request)["records[0]"] == "3":
            return httpx.Response(500, json={"error": "Server overloaded"})
        return httpx.Response(200, json=[{"record_id": "1"}])

    batches = fake_redcap(handler).export_records(["1", "2", "3"], batch_size=2)

    next(batches)
    with pytest.raises(RedcapError, match="Server overloaded"):
        next(batches)


# --- Incremental export ----------------------------------------------------
# On a normal day only records created or changed since the last run are
# fetched, using REDCap's dateRangeBegin. REDCap reads that time in the
# server's own time zone, as "YYYY-MM-DD HH:MM:SS".


def test_without_changed_since_all_record_ids_are_requested():
    seen = {}

    def handler(request):
        seen.update(form_data(request))
        return httpx.Response(200, json=[])

    fake_redcap(handler).export_record_ids("record_id")

    assert "dateRangeBegin" not in seen


def test_changed_since_is_sent_in_the_servers_time_zone():
    seen = {}

    def handler(request):
        seen.update(form_data(request))
        return httpx.Response(200, json=[])

    # Midnight in Nairobi (UTC+3) is 21:00 the day before on a UTC server,
    # the default (the KWTRP REDCap server runs on UTC)
    since = datetime(2026, 11, 21, 0, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
    fake_redcap(handler).export_record_ids("record_id", changed_since=since)

    assert seen["dateRangeBegin"] == "2026-11-20 21:00:00"


def test_the_server_time_zone_can_be_changed():
    seen = {}

    def handler(request):
        seen.update(form_data(request))
        return httpx.Response(200, json=[])

    client = RedcapClient(
        URL, TOKEN, server_timezone="Africa/Nairobi", transport=httpx.MockTransport(handler)
    )
    client.export_record_ids("record_id", changed_since=datetime(2026, 11, 20, 21, 0, tzinfo=UTC))

    assert seen["dateRangeBegin"] == "2026-11-21 00:00:00"


def test_a_time_without_a_time_zone_is_refused():
    # "18:00" means different moments on the laptop, in CI and on the server;
    # guessing could silently skip a few hours of changed records
    client = fake_redcap(lambda request: httpx.Response(200, json=[]))

    with pytest.raises(ValueError, match="time zone"):
        client.export_record_ids("record_id", changed_since=datetime(2026, 11, 20, 18, 0))
