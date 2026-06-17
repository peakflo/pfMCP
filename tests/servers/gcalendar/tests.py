import re
import zoneinfo
import pytest
from datetime import datetime, timedelta

# --- Unit tests: inline copies of timezone logic (no import conflicts with src) ---

TZ_OFFSET_RE = re.compile(r"^[+-]\d{2}:\d{2}$")


def _validate_timezone(tz: str) -> None:
    if tz.upper() == "UTC" or TZ_OFFSET_RE.match(tz):
        return
    try:
        zoneinfo.ZoneInfo(tz)
    except (ValueError, TypeError, zoneinfo.ZoneInfoNotFoundError):
        raise ValueError(
            f"Invalid timezone: '{tz}'. Use IANA name (e.g. 'Asia/Bangkok'), "
            f"UTC offset (e.g. '+07:00'), or 'UTC'."
        )


def _build_event(start_dt: str, end_dt: str, **overrides) -> dict:
    event = {
        "summary": "Test",
        "start": {"dateTime": start_dt} if "T" in start_dt else {"date": start_dt},
        "end": {"dateTime": end_dt} if "T" in end_dt else {"date": end_dt},
        "id": "evt_test",
    }
    event.update(overrides)
    return event


def _format_event(event: dict) -> dict:
    start = event.get("start", {}).get(
        "dateTime", event.get("start", {}).get("date", "N/A")
    )
    end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "N/A"))

    if "T" in start:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        tz_str = dt.strftime("%z")
        tz_label = "UTC" if tz_str == "+0000" else f"UTC{tz_str[:3]}:{tz_str[3:]}"
        start_fmt = dt.strftime("%Y-%m-%d %H:%M") + f" {tz_label}"
    else:
        start_fmt = start

    if "T" in end:
        dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        tz_str = dt.strftime("%z")
        tz_label = "UTC" if tz_str == "+0000" else f"UTC{tz_str[:3]}:{tz_str[3:]}"
        end_fmt = dt.strftime("%Y-%m-%d %H:%M") + f" {tz_label}"
    else:
        end_fmt = end

    return {
        "summary": event.get("summary", "No Title"),
        "start": start_fmt,
        "end": end_fmt,
        "location": event.get("location", "N/A"),
        "id": event.get("id", ""),
        "description": event.get("description", ""),
        "attendees": [a.get("email") for a in event.get("attendees", [])],
    }


def test_validate_timezone_valid_iana():
    _validate_timezone("Asia/Bangkok")
    _validate_timezone("America/New_York")
    _validate_timezone("UTC")
    _validate_timezone("Europe/London")


def test_validate_timezone_valid_offset():
    _validate_timezone("+07:00")
    _validate_timezone("-05:00")
    _validate_timezone("+00:00")


def test_validate_timezone_invalid():
    with pytest.raises(ValueError, match="Invalid timezone"):
        _validate_timezone("Fake/Zone")
    with pytest.raises(ValueError, match="Invalid timezone"):
        _validate_timezone("invalid")
    with pytest.raises(ValueError, match="Invalid timezone"):
        _validate_timezone("12:00")


def test_format_event_positive_offset():
    event = _build_event("2026-06-18T14:00:00+07:00", "2026-06-18T15:00:00+07:00")
    result = _format_event(event)
    assert result["start"] == "2026-06-18 14:00 UTC+07:00"
    assert result["end"] == "2026-06-18 15:00 UTC+07:00"


def test_format_event_negative_offset():
    event = _build_event("2026-06-18T10:00:00-04:00", "2026-06-18T11:00:00-04:00")
    result = _format_event(event)
    assert result["start"] == "2026-06-18 10:00 UTC-04:00"
    assert result["end"] == "2026-06-18 11:00 UTC-04:00"


def test_format_event_utc():
    event = _build_event("2026-06-18T14:00:00Z", "2026-06-18T15:00:00Z")
    result = _format_event(event)
    assert result["start"] == "2026-06-18 14:00 UTC"
    assert result["end"] == "2026-06-18 15:00 UTC"


def test_format_event_utc_plus_zero_zero():
    event = _build_event("2026-06-18T14:00:00+00:00", "2026-06-18T15:00:00+00:00")
    result = _format_event(event)
    assert result["start"] == "2026-06-18 14:00 UTC"
    assert result["end"] == "2026-06-18 15:00 UTC"


def test_format_event_all_day():
    event = _build_event("2026-06-18", "2026-06-19")
    result = _format_event(event)
    assert result["start"] == "2026-06-18"
    assert result["end"] == "2026-06-19"


def test_format_event_half_hour_offset():
    event = _build_event("2026-06-18T09:00:00+05:30", "2026-06-18T10:00:00+05:30")
    result = _format_event(event)
    assert result["start"] == "2026-06-18 09:00 UTC+05:30"
    assert result["end"] == "2026-06-18 10:00 UTC+05:30"


def test_format_event_preserves_other_fields():
    event = _build_event(
        "2026-06-18T09:00:00+05:30",
        "2026-06-18T10:00:00+05:30",
        location="Room 1",
        description="Meeting notes",
        attendees=[{"email": "a@b.com"}, {"email": "c@d.com"}],
    )
    result = _format_event(event)
    assert result["summary"] == "Test"
    assert result["location"] == "Room 1"
    assert result["id"] == "evt_test"
    assert result["description"] == "Meeting notes"
    assert result["attendees"] == ["a@b.com", "c@d.com"]


# --- Integration tests (require API credentials) ---


@pytest.mark.asyncio
async def test_list_resources(client):
    """Test listing calendars from Google Calendar"""
    response = await client.list_resources()
    assert (
        response and hasattr(response, "resources") and len(response.resources)
    ), f"Invalid list resources response: {response}"

    print("Calendars found:")
    for resource in response.resources:
        print(f"  - {resource.name} ({resource.uri}) - Type: {resource.mimeType}")

    print("✅ Successfully listed calendars")


@pytest.mark.asyncio
async def test_read_calendar(client):
    """Test reading a specific calendar"""
    response = await client.list_resources()
    assert (
        response and hasattr(response, "resources") and len(response.resources)
    ), f"Invalid list resources response: {response}"

    resources = response.resources
    regular_calendar = next((r for r in resources), None)

    if regular_calendar:
        calendar_response = await client.read_resource(regular_calendar.uri)
        assert len(
            calendar_response.contents[0].text
        ), f"Response should contain calendar events: {calendar_response}"
        print("Calendar events read:")
        print(f"\t{calendar_response.contents[0].text}")

    print("✅ Successfully read calendar resources")


@pytest.mark.asyncio
async def test_list_events_tool(client):
    """Test the list_events tool functionality"""
    response = await client.process_query(
        "Use the list_events tool to show my calendar events for the next week."
        + "\n\nIf successful, start your response with 'Found these events:'"
    )
    assert response, "No response received when listing events"
    assert "found" in response.lower(), f"Unexpected response format: {response}"
    print("List events (default parameters):")
    print(f"\t{response}")

    response = await client.process_query(
        "Use the list_events tool to show me events for the next 7 days with a maximum of 5 results."
        + "\n\nIf successful, start your response with 'Found these events:'"
    )
    assert response, "No response received when listing events with custom parameters"
    assert "found" in response.lower(), f"Unexpected response format: {response}"
    print("List events (custom parameters):")
    print(f"\t{response}")
    print("✅ Successfully tested list_events tool")


@pytest.mark.asyncio
async def test_create_event_tool(client):
    """Test the create_event tool functionality"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    response = await client.process_query(
        f"Use the create_event tool to create a meeting called 'Test Meeting' for tomorrow ({tomorrow}) at 10:00 AM, ending at 11:00 AM."
        + "\n\nIf successful, start your response with 'Event created successfully, Event ID: {event_id}\nEvent details: {event_details}'"
    )
    assert response, "No response received when creating an event"
    assert (
        "event created successfully" in response.lower()
    ), f"Event creation failed: {response}"

    event_id = None
    for line in response.split("\n"):
        if "Event ID:" in line:
            event_id = line.split("Event ID:")[1].strip()
            break
    assert event_id, "Could not find event ID in the response"
    print("Create event result:")
    print(f"\t{response}")
    print(f"\tEvent ID: {event_id}")
    print("✅ Successfully tested create_event tool")
    return event_id


@pytest.mark.asyncio
async def test_update_event_tool(client):
    """Test the update_event tool functionality"""
    event_id = await test_create_event_tool(client)
    response = await client.process_query(
        f"Use the update_event tool to update the event with ID '{event_id}'. Change the title to 'Updated Test Meeting' and the description to 'This is a test description'."
        + "\n\nIf successful, start your response with 'Event updated successfully. Updated Test Meeting: "
    )
    assert response, "No response received when updating an event"
    assert (
        "event updated successfully" in response.lower()
    ), f"Event update failed: {response}"
    assert (
        "updated test meeting" in response.lower()
    ), "Updated title not found in response"
    print("Update event result:")
    print(f"\t{response}")
    print("✅ Successfully tested update_event tool")
