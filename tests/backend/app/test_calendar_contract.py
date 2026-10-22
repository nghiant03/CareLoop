from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from backend.app import main


@pytest.mark.parametrize("hours, minutes, label, expected_date, expected_offset", [
    (8, 0, "SGT", "2026-10-11", 480),
    (-7, 0, "PDT", "2026-10-10", -420),
    (5, 30, "IST", "2026-10-11", 330),
    (0, 0, "UTC", "2026-10-10", 0),
])
def test_calendar_uses_server_local_date_and_offset(
    client, monkeypatch, hours, minutes, label, expected_date, expected_offset,
):
    instant = datetime(2026, 10, 10, 23, 30, tzinfo=UTC)
    server_zone = timezone(timedelta(hours=hours, minutes=minutes), name=label)
    local_now = instant.astimezone(server_zone)
    clock = Mock(return_value=local_now)
    monkeypatch.setattr(main, "_server_local_now", clock)

    response = client.get("/calendar")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "today": expected_date, "timezone": label, "utc_offset_minutes": expected_offset,
    }
    assert response.json()["today"] == local_now.date().isoformat()
    offset = local_now.utcoffset()
    assert offset is not None
    assert response.json()["utc_offset_minutes"] == offset.total_seconds() / 60
    clock.assert_called_once_with()


def test_calendar_samples_clock_once_per_request(client, monkeypatch):
    before_midnight = datetime(2026, 10, 11, 23, 59, 59, tzinfo=timezone(timedelta(hours=8), "SGT"))
    after_midnight = before_midnight + timedelta(seconds=2)
    clock = Mock(side_effect=[before_midnight, after_midnight])
    monkeypatch.setattr(main, "_server_local_now", clock)

    assert client.get("/calendar").json()["today"] == "2026-10-11"
    assert clock.call_count == 1
    assert client.get("/calendar").json()["today"] == "2026-10-12"
    assert clock.call_count == 2


def test_server_clock_localizes_one_instant(monkeypatch):
    datetime_clock = Mock()
    local_instant = datetime(2026, 10, 11, 7, 30, tzinfo=timezone(timedelta(hours=8), "SGT"))
    datetime_clock.now.return_value.astimezone.return_value = local_instant
    monkeypatch.setattr(main, "datetime", datetime_clock)

    assert main._server_local_now() is local_instant
    datetime_clock.now.assert_called_once_with()
    datetime_clock.now.return_value.astimezone.assert_called_once_with()


def test_calendar_documents_exact_response_shape(client):
    document = client.get("/openapi.json").json()
    response = document["paths"]["/calendar"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith("/CalendarResponse")
    schema = document["components"]["schemas"]["CalendarResponse"]
    assert set(schema["properties"]) == set(schema["required"]) == {
        "today", "timezone", "utc_offset_minutes",
    }
    assert schema["properties"]["today"]["type"] == "string"
    assert schema["properties"]["today"]["format"] == "date"
    assert schema["properties"]["timezone"]["type"] == "string"
    assert schema["properties"]["utc_offset_minutes"]["type"] == "number"
