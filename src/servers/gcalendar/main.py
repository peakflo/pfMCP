import os
import sys
from typing import Optional, Iterable
from datetime import datetime, timedelta

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
import re
import zoneinfo
from pathlib import Path

from mcp.types import (
    AnyUrl,
    Resource,
    TextContent,
    Tool,
    ImageContent,
    EmbeddedResource,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.utils.google.util import authenticate_and_save_credentials, get_credentials

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SERVICE_NAME = Path(__file__).parent.name
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)

# Regex for UTC offset format like +07:00, -05:00
TZ_OFFSET_RE = re.compile(r"^[+-]\d{2}:\d{2}$")


def _validate_timezone(tz: str) -> None:
    """Validate a timezone string (IANA name or UTC offset)."""
    if tz.upper() == "UTC" or TZ_OFFSET_RE.match(tz):
        return
    try:
        zoneinfo.ZoneInfo(tz)
    except (ValueError, TypeError, zoneinfo.ZoneInfoNotFoundError):
        raise ValueError(
            f"Invalid timezone: '{tz}'. Use IANA name (e.g. 'Asia/Bangkok'), "
            f"UTC offset (e.g. '+07:00'), or 'UTC'."
        )


async def create_calendar_service(user_id, api_key=None):
    """Create a new Calendar service instance for this request"""
    credentials = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return build("calendar", "v3", credentials=credentials)


def format_event(event):
    """Format a calendar event for display"""
    start = event.get("start", {}).get(
        "dateTime", event.get("start", {}).get("date", "N/A")
    )
    end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "N/A"))

    # Format start time
    if "T" in start:  # This is a datetime
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        tz_str = start_dt.strftime("%z")
        if tz_str == "+0000":
            tz_label = "UTC"
        else:
            tz_label = f"UTC{tz_str[:3]}:{tz_str[3:]}"
        start_formatted = start_dt.strftime("%Y-%m-%d %H:%M") + f" {tz_label}"
    else:  # This is a date
        start_formatted = start

    # Format end time
    if "T" in end:  # This is a datetime
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        tz_str = end_dt.strftime("%z")
        if tz_str == "+0000":
            tz_label = "UTC"
        else:
            tz_label = f"UTC{tz_str[:3]}:{tz_str[3:]}"
        end_formatted = end_dt.strftime("%Y-%m-%d %H:%M") + f" {tz_label}"
    else:  # This is a date
        end_formatted = end

    return {
        "summary": event.get("summary", "No Title"),
        "start": start_formatted,
        "end": end_formatted,
        "location": event.get("location", "N/A"),
        "id": event.get("id", ""),
        "description": event.get("description", ""),
        "attendees": [a.get("email") for a in event.get("attendees", [])],
    }


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("gcalendar-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List calendars"""
        logger.info(
            f"Listing calendars for user: {server.user_id} with cursor: {cursor}"
        )

        calendar_service = await create_calendar_service(
            server.user_id, api_key=server.api_key
        )

        calendars = calendar_service.calendarList().list().execute()
        calendar_items = calendars.get("items", [])

        resources = []
        for calendar in calendar_items:
            resource = Resource(
                uri=f"gcalendar://calendar/{calendar['id']}",
                mimeType="application/json",
                name=calendar["summary"],
                description=calendar.get("description", ""),
            )
            resources.append(resource)

        return resources

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read calendar or events by URI"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        calendar_service = await create_calendar_service(
            server.user_id, api_key=server.api_key
        )

        # Parse the URI to extract resource_type and resource_id
        uri_parts = str(uri).split("://")
        if len(uri_parts) != 2:
            return [
                ReadResourceContents(
                    content="Invalid URI format", mime_type="text/plain"
                )
            ]

        path_parts = uri_parts[1].split("/")
        if len(path_parts) < 2:
            return [
                ReadResourceContents(content="Invalid URI path", mime_type="text/plain")
            ]

        resource_type = path_parts[0]
        resource_id = path_parts[1]

        # Handle calendar resources
        try:
            if resource_type == "calendar":
                events_result = (
                    calendar_service.events()
                    .list(
                        calendarId=resource_id,
                        timeMin=datetime.utcnow().isoformat() + "Z",
                        maxResults=10,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

                events = events_result.get("items", [])
                formatted_events = [format_event(event) for event in events]

                calendar = (
                    calendar_service.calendars().get(calendarId=resource_id).execute()
                )

                content = f"Calendar: {calendar.get('summary', 'Unknown')}\n\n"
                content += "Upcoming events:\n\n"

                for i, event in enumerate(formatted_events, 1):
                    content += f"{i}. {event['summary']}\n"
                    content += f"   When: {event['start']} to {event['end']}\n"
                    if event["location"] != "N/A":
                        content += f"   Where: {event['location']}\n"
                    if event["attendees"]:
                        content += f"   Attendees: {', '.join(event['attendees'])}\n"
                    content += "\n"

                return [ReadResourceContents(content=content, mime_type="text/plain")]
            else:
                return [
                    ReadResourceContents(
                        content=f"Unsupported resource type: {resource_type}",
                        mime_type="text/plain",
                    )
                ]
        except HttpError as error:
            logger.error(f"Error reading calendar: {error}")
            return [
                ReadResourceContents(
                    content=f"Error reading calendar: {error}", mime_type="text/plain"
                )
            ]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools"""
        logger.info(f"Listing tools for user: {server.user_id}")
        return [
            Tool(
                name="list_events",
                description="List events from Google Calendar for a specified time range. Times are shown in the calendar's local timezone with offset (e.g. '14:00 +07:00').",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (optional - defaults to primary)",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look ahead (optional - defaults to 7)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of events to return (optional - defaults to 10)",
                        },
                    },
                },
            ),
            Tool(
                name="create_event",
                description="Create a new event in Google Calendar. Datetime inputs are treated as local time in the specified timezone (defaults to UTC if omitted).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (optional - defaults to primary)",
                        },
                        "summary": {"type": "string", "description": "Event title"},
                        "start_datetime": {
                            "type": "string",
                            "description": "Start date/time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD). Treated as local time in the given timezone (defaults to UTC).",
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": "End date/time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD). Treated as local time in the given timezone (defaults to UTC).",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "Timezone for start_datetime and end_datetime (e.g. 'Asia/Bangkok', 'America/New_York', '+07:00'). Defaults to 'UTC' if omitted.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description (optional)",
                        },
                        "location": {
                            "type": "string",
                            "description": "Event location (optional)",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of attendee emails (optional)",
                        },
                    },
                    "required": ["summary", "start_datetime", "end_datetime"],
                },
            ),
            Tool(
                name="update_event",
                description="Update an existing event in Google Calendar. Datetime inputs are treated as local time in the specified timezone (defaults to UTC if omitted).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (optional - defaults to primary)",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "Event ID to update",
                        },
                        "summary": {
                            "type": "string",
                            "description": "New event title (optional)",
                        },
                        "start_datetime": {
                            "type": "string",
                            "description": "New start date/time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD). Treated as local time in the given timezone (defaults to UTC). (optional)",
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": "New end date/time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD). Treated as local time in the given timezone (defaults to UTC). (optional)",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "Timezone for start_datetime and end_datetime (e.g. 'Asia/Bangkok', 'America/New_York', '+07:00'). Defaults to 'UTC' if omitted.",
                        },
                        "description": {
                            "type": "string",
                            "description": "New event description (optional)",
                        },
                        "location": {
                            "type": "string",
                            "description": "New event location (optional)",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New list of attendee emails (optional)",
                        },
                    },
                    "required": ["event_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool execution requests"""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        if arguments is None:
            arguments = {}

        calendar_service = await create_calendar_service(
            server.user_id, api_key=server.api_key
        )

        try:
            if name == "list_events":
                calendar_id = arguments.get("calendar_id", "primary")
                days = int(arguments.get("days", 7))
                max_results = int(arguments.get("max_results", 10))

                time_min = datetime.utcnow().isoformat() + "Z"
                time_max = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

                events_result = (
                    calendar_service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

                events = events_result.get("items", [])
                formatted_events = [format_event(event) for event in events]

                response = (
                    f"Found {len(formatted_events)} events in the next {days} days:\n\n"
                )

                for i, event in enumerate(formatted_events, 1):
                    response += f"{i}. {event['summary']}\n"
                    response += f"   ID: {event['id']}\n"
                    response += f"   When: {event['start']} to {event['end']}\n"
                    if event["location"] != "N/A":
                        response += f"   Where: {event['location']}\n"
                    if event["description"]:
                        response += f"   Description: {event['description']}\n"
                    if event["attendees"]:
                        response += f"   Attendees: {', '.join(event['attendees'])}\n"
                    response += "\n"

                if not formatted_events:
                    response = f"No events found in the next {days} days."

                return [TextContent(type="text", text=response)]

            elif name == "create_event":
                if not all(
                    k in arguments
                    for k in ["summary", "start_datetime", "end_datetime"]
                ):
                    raise ValueError(
                        "Missing required parameters: summary, start_datetime, end_datetime"
                    )

                calendar_id = arguments.get("calendar_id", "primary")
                summary = arguments["summary"]
                description = arguments.get("description", "")
                location = arguments.get("location", "")
                attendees = arguments.get("attendees", [])
                timezone_str = arguments.get("timezone", "UTC")

                # Validate timezone
                _validate_timezone(timezone_str)

                # Process start and end times
                start_datetime = arguments["start_datetime"]
                end_datetime = arguments["end_datetime"]

                # Check if full datetime or just date
                start_has_time = len(start_datetime.split()) > 1
                end_has_time = len(end_datetime.split()) > 1

                event = {
                    "summary": summary,
                    "description": description,
                    "location": location,
                }

                # Handle start time
                if start_has_time:
                    try:
                        dt = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M")
                        event["start"] = {
                            "dateTime": dt.isoformat(),
                            "timeZone": timezone_str,
                        }
                    except ValueError:
                        raise ValueError(
                            "Invalid start datetime format. Use YYYY-MM-DD HH:MM"
                        )
                else:
                    event["start"] = {"date": start_datetime}

                # Handle end time
                if end_has_time:
                    try:
                        dt = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M")
                        event["end"] = {
                            "dateTime": dt.isoformat(),
                            "timeZone": timezone_str,
                        }
                    except ValueError:
                        raise ValueError(
                            "Invalid end datetime format. Use YYYY-MM-DD HH:MM"
                        )
                else:
                    event["end"] = {"date": end_datetime}

                # Add attendees if provided
                if attendees:
                    event["attendees"] = [{"email": email} for email in attendees]

                created_event = (
                    calendar_service.events()
                    .insert(calendarId=calendar_id, body=event)
                    .execute()
                )

                response = f"Event created successfully!\n"
                response += f"Title: {summary}\n"
                if start_has_time:
                    response += f"Start: {start_datetime} ({timezone_str})\n"
                else:
                    response += f"Start Date: {start_datetime}\n"

                if end_has_time:
                    response += f"End: {end_datetime} ({timezone_str})\n"
                else:
                    response += f"End Date: {end_datetime}\n"

                if location:
                    response += f"Location: {location}\n"
                if description:
                    response += f"Description: {description}\n"
                if attendees:
                    response += f"Attendees: {', '.join(attendees)}\n"

                response += f"\nEvent ID: {created_event['id']}"
                response += f"\nEvent Link: {created_event.get('htmlLink', 'N/A')}"

                return [TextContent(type="text", text=response)]

            elif name == "update_event":
                if "event_id" not in arguments:
                    raise ValueError("Missing required parameter: event_id")

                calendar_id = arguments.get("calendar_id", "primary")
                event_id = arguments["event_id"]
                timezone_str = arguments.get("timezone")

                if timezone_str is not None:
                    _validate_timezone(timezone_str)

                # First get the existing event
                event = (
                    calendar_service.events()
                    .get(calendarId=calendar_id, eventId=event_id)
                    .execute()
                )

                # Update fields that were provided
                if "summary" in arguments:
                    event["summary"] = arguments["summary"]

                if "description" in arguments:
                    event["description"] = arguments["description"]

                if "location" in arguments:
                    event["location"] = arguments["location"]

                # Process start time if provided
                if "start_datetime" in arguments:
                    start_datetime = arguments["start_datetime"]
                    start_has_time = len(start_datetime.split()) > 1
                    tz = (
                        timezone_str
                        if timezone_str
                        else event.get("start", {}).get("timeZone", "UTC")
                    )

                    if start_has_time:
                        try:
                            dt = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M")
                            event["start"] = {
                                "dateTime": dt.isoformat(),
                                "timeZone": tz,
                            }
                        except ValueError:
                            raise ValueError(
                                "Invalid start datetime format. Use YYYY-MM-DD HH:MM"
                            )
                    else:
                        event["start"] = {"date": start_datetime}

                # Process end time if provided
                if "end_datetime" in arguments:
                    end_datetime = arguments["end_datetime"]
                    end_has_time = len(end_datetime.split()) > 1
                    tz = (
                        timezone_str
                        if timezone_str
                        else event.get("end", {}).get("timeZone", "UTC")
                    )

                    if end_has_time:
                        try:
                            dt = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M")
                            event["end"] = {
                                "dateTime": dt.isoformat(),
                                "timeZone": tz,
                            }
                        except ValueError:
                            raise ValueError(
                                "Invalid end datetime format. Use YYYY-MM-DD HH:MM"
                            )
                    else:
                        event["end"] = {"date": end_datetime}

                # Update attendees if provided
                if "attendees" in arguments:
                    event["attendees"] = [
                        {"email": email} for email in arguments["attendees"]
                    ]

                # Update the event
                updated_event = (
                    calendar_service.events()
                    .update(calendarId=calendar_id, eventId=event_id, body=event)
                    .execute()
                )

                formatted_event = format_event(updated_event)

                response = f"Event updated successfully!\n"
                response += f"Title: {formatted_event['summary']}\n"
                response += (
                    f"When: {formatted_event['start']} to {formatted_event['end']}\n"
                )

                if formatted_event["location"] != "N/A":
                    response += f"Location: {formatted_event['location']}\n"
                if formatted_event["description"]:
                    response += f"Description: {formatted_event['description']}\n"
                if formatted_event["attendees"]:
                    response += (
                        f"Attendees: {', '.join(formatted_event['attendees'])}\n"
                    )

                response += f"\nEvent Link: {updated_event.get('htmlLink', 'N/A')}"

                return [TextContent(type="text", text=response)]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except HttpError as error:
            error_message = f"Error accessing Google Calendar: {error}"
            logger.error(error_message)
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"Error executing tool {name}: {str(e)}"
            logger.error(error_message)
            return [TextContent(type="text", text=error_message)]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="gcalendar-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Main handler allows users to auth
if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        # Run authentication flow
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
