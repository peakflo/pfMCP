import os
from memory_profiler import profile
import sys
from typing import Optional, List, Dict, Any

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

"""
Main entry point for the Google Sheets server integration.

This module handles:
1) Google OAuth authentication and credential handling.
2) Creation of a guMCP server exposing tools to interact with the Sheets API.
3) A simple CLI flow for local authentication.
"""

import base64
import logging
import json
from pathlib import Path

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import re

from src.utils.google.util import authenticate_and_save_credentials
from src.auth.factory import create_auth_client

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("gsheets-server")

SERVICE_NAME = Path(__file__).parent.name
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# @profile
def extract_spreadsheet_id(sheet_url: str) -> str:
    """Extracts the spreadsheetId from a Google Sheets URL.

    Args:
        sheet_url (str): The full URL of the Google Sheets.

    Returns:
        str: The extracted spreadsheet ID.

    Raises:
        ValueError: If the URL is invalid or ID is not found.
    """
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
    if match:
        return match.group(1)
    raise ValueError("Invalid Google Sheets URL: could not extract spreadsheetId")


# @profile
async def get_credentials(user_id, api_key=None):
    """Get credentials for the specified user

    Args:
        user_id (str): The identifier of the user whose credentials are needed.
        api_key (Optional[str]): Optional API key for different environments.

    Returns:
        Credentials: The Google OAuth2 credentials for the specified user.

    Raises:
        ValueError: If no valid credentials can be found.
    """
    # Get auth client
    auth_client = create_auth_client(api_key=api_key)

    # Get credentials for this user
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    def handle_missing_credentials():
        error_str = f"Credentials not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += "Please run with 'auth' argument first."
        logging.error(error_str)
        raise ValueError(f"Credentials not found for user {user_id}")

    if not credentials_data:
        handle_missing_credentials()

    token = credentials_data.get("token")
    if token:
        return Credentials.from_authorized_user_info(credentials_data)

    # If the auth client doesn't return key 'token', but instead returns 'access_token',
    # assume that refreshing is taken care of on the auth client side
    token = credentials_data.get("access_token")
    if token:
        return Credentials(token=token)

    handle_missing_credentials()


# @profile
async def create_sheets_service(user_id, api_key=None):
    """Create a new Sheets service instance for this request

    Args:
        user_id (str): The identifier of the user for whom the service is created.
        api_key (Optional[str]): Optional API key if needed.

    Returns:
        googleapiclient.discovery.Resource: Authorized Sheets API client.
    """
    credentials = await get_credentials(user_id, api_key=api_key)
    return build("sheets", "v4", credentials=credentials)


# @profile
async def create_drive_service(user_id, api_key=None):
    """Create a new Drive service instance for this request

    Args:
        user_id (str): The identifier of the user for whom the service is created.
        api_key (Optional[str]): Optional API key if needed.

    Returns:
        googleapiclient.discovery.Resource: Authorized Drive API client.
    """
    credentials = await get_credentials(user_id, api_key=api_key)
    return build("drive", "v3", credentials=credentials)


# @profile
def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context

    Args:
        user_id (str): The identifier of the user for this server session.
        api_key (Optional[str]): Optional API key for server context.

    Returns:
        Server: An instance of the Server class configured for Google Sheets.
    """
    server = Server("gsheets-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    # @profile
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="create-spreadsheet",
                description="Create a new Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
            types.Tool(
                name="get-sheet-data",
                description="Get data from a specific sheet in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "range": {"type": "string"},
                        "include_grid_data": {"type": "boolean"},
                    },
                    "required": ["spreadsheet_url", "sheet"],
                },
            ),
            types.Tool(
                name="get-sheet-formulas",
                description="Get formulas from a specific sheet in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "range": {"type": "string"},
                    },
                    "required": ["spreadsheet_url", "sheet"],
                },
            ),
            types.Tool(
                name="update-cells",
                description="Update cells in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "range": {"type": "string"},
                        "data": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "required": ["spreadsheet_url", "sheet", "range", "data"],
                },
            ),
            types.Tool(
                name="batch-update-cells",
                description="Batch update multiple ranges in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "ranges": {"type": "object"},
                    },
                    "required": ["spreadsheet_url", "sheet", "ranges"],
                },
            ),
            types.Tool(
                name="add-rows",
                description="Add rows to a sheet in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "count": {"type": "integer"},
                        "start_row": {"type": "integer"},
                    },
                    "required": ["spreadsheet_url", "sheet", "count"],
                },
            ),
            types.Tool(
                name="add-columns",
                description="Add columns to a sheet in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "count": {"type": "integer"},
                        "start_column": {"type": "integer"},
                    },
                    "required": ["spreadsheet_url", "sheet", "count"],
                },
            ),
            types.Tool(
                name="list-sheets",
                description="List all sheets in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {"spreadsheet_url": {"type": "string"}},
                    "required": ["spreadsheet_url"],
                },
            ),
            types.Tool(
                name="create-sheet",
                description="Create a new sheet tab in an existing Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["spreadsheet_url", "title"],
                },
            ),
            types.Tool(
                name="copy-sheet",
                description="Copy a sheet from one spreadsheet to another in Google Sheets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_spreadsheet_url": {"type": "string"},
                        "source_sheet": {"type": "string"},
                        "destination_spreadsheet_url": {"type": "string"},
                        "destination_sheet": {"type": "string"},
                    },
                    "required": [
                        "source_spreadsheet_url",
                        "source_sheet",
                        "destination_spreadsheet_url",
                        "destination_sheet",
                    ],
                },
            ),
            types.Tool(
                name="rename-sheet",
                description="Rename a sheet in a Google Spreadsheet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "sheet": {"type": "string"},
                        "new_name": {"type": "string"},
                    },
                    "required": ["spreadsheet_url", "sheet", "new_name"],
                },
            ),
            types.Tool(
                name="get-multiple-sheet-data",
                description="Get data from multiple specific ranges in Google Spreadsheets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "spreadsheet_url": {"type": "string"},
                                    "sheet": {"type": "string"},
                                    "range": {"type": "string"},
                                },
                                "required": ["spreadsheet_url", "sheet", "range"],
                            },
                        },
                    },
                    "required": ["queries"],
                },
            ),
            types.Tool(
                name="get-multiple-spreadsheet-summary",
                description="Get a summary of multiple Google Spreadsheets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "rows_to_fetch": {"type": "integer"},
                    },
                    "required": ["spreadsheet_urls"],
                },
            ),
            types.Tool(
                name="list-spreadsheets",
                description="List all spreadsheets in Google Drive",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            types.Tool(
                name="share-spreadsheet",
                description="Share a Google Spreadsheet with multiple users",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "recipients": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "email_address": {"type": "string"},
                                    "role": {"type": "string"},
                                },
                                "required": ["email_address", "role"],
                            },
                        },
                        "send_notification": {"type": "boolean"},
                    },
                    "required": ["spreadsheet_url", "recipients"],
                },
            ),
            types.Tool(
                name="append-values",
                description="Append values to a sheet in Google Sheets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "range": {"type": "string"},
                        "values": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "required": ["spreadsheet_url", "range", "values"],
                },
            ),
            types.Tool(
                name="clear-values",
                description="Clear a sheet range in Google Sheets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_url": {"type": "string"},
                        "range": {"type": "string"},
                    },
                    "required": ["spreadsheet_url", "range"],
                },
            ),
        ]

    @server.call_tool()
    # @profile
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch and handle tool execution

        Args:
            name (str): The name of the tool to call.
            arguments (dict | None): The arguments required by the tool.

        Returns:
            list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
                The resulting content from the executed tool.

        Raises:
            ValueError: If an unknown tool name is provided.
        """
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        # Extract spreadsheet IDs from URLs where needed
        if "spreadsheet_url" in arguments:
            arguments["spreadsheet_id"] = extract_spreadsheet_id(
                arguments["spreadsheet_url"]
            )
        if "source_spreadsheet_url" in arguments:
            arguments["source_spreadsheet_id"] = extract_spreadsheet_id(
                arguments["source_spreadsheet_url"]
            )
        if "destination_spreadsheet_url" in arguments:
            arguments["destination_spreadsheet_id"] = extract_spreadsheet_id(
                arguments["destination_spreadsheet_url"]
            )

        sheets_service = await create_sheets_service(server.user_id, server.api_key)
        drive_service = await create_drive_service(server.user_id, server.api_key)

        try:
            if name == "create-spreadsheet":
                title = arguments.get("title", "New Spreadsheet")
                file_body = {
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
                spreadsheet = (
                    drive_service.files()
                    .create(supportsAllDrives=True, body=file_body, fields="id, name")
                    .execute()
                )

                spreadsheet_id = spreadsheet.get("id")
                sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "spreadsheetId": spreadsheet_id,
                                "title": spreadsheet.get("name", title),
                                "url": sheet_url,
                            },
                            indent=2,
                        ),
                    )
                ]

            if name == "get-sheet-data":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                range_str = arguments.get("range")
                include_grid_data = arguments.get("include_grid_data", False)

                # Construct the range
                if range_str:
                    full_range = f"{sheet}!{range_str}"
                else:
                    full_range = sheet

                if include_grid_data:
                    result = (
                        sheets_service.spreadsheets()
                        .get(
                            spreadsheetId=spreadsheet_id,
                            ranges=[full_range],
                            includeGridData=True,
                        )
                        .execute()
                    )
                else:
                    values_result = (
                        sheets_service.spreadsheets()
                        .values()
                        .get(spreadsheetId=spreadsheet_id, range=full_range)
                        .execute()
                    )

                    result = {
                        "spreadsheetId": spreadsheet_id,
                        "valueRanges": [
                            {
                                "range": full_range,
                                "values": values_result.get("values", []),
                            }
                        ],
                    }

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "get-sheet-formulas":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                range_str = arguments.get("range")

                # Construct the range
                if range_str:
                    full_range = f"{sheet}!{range_str}"
                else:
                    full_range = sheet

                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .get(
                        spreadsheetId=spreadsheet_id,
                        range=full_range,
                        valueRenderOption="FORMULA",
                    )
                    .execute()
                )

                formulas = result.get("values", [])
                return [
                    types.TextContent(type="text", text=json.dumps(formulas, indent=2))
                ]

            if name == "update-cells":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                range_str = arguments["range"]
                data = arguments["data"]

                full_range = f"{sheet}!{range_str}"
                value_range_body = {"values": data}

                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=spreadsheet_id,
                        range=full_range,
                        valueInputOption="USER_ENTERED",
                        body=value_range_body,
                    )
                    .execute()
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "batch-update-cells":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                ranges = arguments["ranges"]

                data = []
                for range_str, values in ranges.items():
                    full_range = f"{sheet}!{range_str}"
                    data.append({"range": full_range, "values": values})

                batch_body = {"valueInputOption": "USER_ENTERED", "data": data}

                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .batchUpdate(spreadsheetId=spreadsheet_id, body=batch_body)
                    .execute()
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "add-rows":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                count = arguments["count"]
                start_row = arguments.get("start_row")

                # Get sheet ID
                spreadsheet = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=spreadsheet_id)
                    .execute()
                )
                sheet_id = None

                for s in spreadsheet["sheets"]:
                    if s["properties"]["title"] == sheet:
                        sheet_id = s["properties"]["sheetId"]
                        break

                if sheet_id is None:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": f"Sheet '{sheet}' not found"}, indent=2
                            ),
                        )
                    ]

                request_body = {
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": (
                                        start_row if start_row is not None else 0
                                    ),
                                    "endIndex": (
                                        start_row if start_row is not None else 0
                                    )
                                    + count,
                                },
                                "inheritFromBefore": start_row is not None
                                and start_row > 0,
                            }
                        }
                    ]
                }

                result = (
                    sheets_service.spreadsheets()
                    .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
                    .execute()
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "add-columns":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                count = arguments["count"]
                start_column = arguments.get("start_column")

                # Get sheet ID
                spreadsheet = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=spreadsheet_id)
                    .execute()
                )
                sheet_id = None

                for s in spreadsheet["sheets"]:
                    if s["properties"]["title"] == sheet:
                        sheet_id = s["properties"]["sheetId"]
                        break

                if sheet_id is None:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": f"Sheet '{sheet}' not found"}, indent=2
                            ),
                        )
                    ]

                request_body = {
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": (
                                        start_column if start_column is not None else 0
                                    ),
                                    "endIndex": (
                                        start_column if start_column is not None else 0
                                    )
                                    + count,
                                },
                                "inheritFromBefore": start_column is not None
                                and start_column > 0,
                            }
                        }
                    ]
                }

                result = (
                    sheets_service.spreadsheets()
                    .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
                    .execute()
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "list-sheets":
                spreadsheet_id = arguments["spreadsheet_id"]
                spreadsheet = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=spreadsheet_id)
                    .execute()
                )
                sheet_names = [
                    sheet["properties"]["title"] for sheet in spreadsheet["sheets"]
                ]
                return [
                    types.TextContent(
                        type="text", text=json.dumps(sheet_names, indent=2)
                    )
                ]

            if name == "create-sheet":
                spreadsheet_id = arguments["spreadsheet_id"]
                title = arguments["title"]

                request_body = {
                    "requests": [{"addSheet": {"properties": {"title": title}}}]
                }

                result = (
                    sheets_service.spreadsheets()
                    .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
                    .execute()
                )

                new_sheet_props = result["replies"][0]["addSheet"]["properties"]
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "sheetId": new_sheet_props["sheetId"],
                                "title": new_sheet_props["title"],
                                "index": new_sheet_props.get("index"),
                                "spreadsheetId": spreadsheet_id,
                            },
                            indent=2,
                        ),
                    )
                ]

            if name == "copy-sheet":
                source_spreadsheet_id = arguments["source_spreadsheet_id"]
                source_sheet = arguments["source_sheet"]
                destination_spreadsheet_id = arguments["destination_spreadsheet_id"]
                destination_sheet = arguments["destination_sheet"]

                # Get source sheet ID
                src = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=source_spreadsheet_id)
                    .execute()
                )
                src_sheet_id = None

                for s in src["sheets"]:
                    if s["properties"]["title"] == source_sheet:
                        src_sheet_id = s["properties"]["sheetId"]
                        break

                if src_sheet_id is None:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": f"Source sheet '{source_sheet}' not found"},
                                indent=2,
                            ),
                        )
                    ]

                # Copy the sheet
                copy_result = (
                    sheets_service.spreadsheets()
                    .sheets()
                    .copyTo(
                        spreadsheetId=source_spreadsheet_id,
                        sheetId=src_sheet_id,
                        body={"destinationSpreadsheetId": destination_spreadsheet_id},
                    )
                    .execute()
                )

                # Rename if needed
                if "title" in copy_result and copy_result["title"] != destination_sheet:
                    copy_sheet_id = copy_result["sheetId"]
                    rename_request = {
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": copy_sheet_id,
                                        "title": destination_sheet,
                                    },
                                    "fields": "title",
                                }
                            }
                        ]
                    }

                    rename_result = (
                        sheets_service.spreadsheets()
                        .batchUpdate(
                            spreadsheetId=destination_spreadsheet_id,
                            body=rename_request,
                        )
                        .execute()
                    )

                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"copy": copy_result, "rename": rename_result}, indent=2
                            ),
                        )
                    ]

                return [
                    types.TextContent(
                        type="text", text=json.dumps({"copy": copy_result}, indent=2)
                    )
                ]

            if name == "rename-sheet":
                spreadsheet_id = arguments["spreadsheet_id"]
                sheet = arguments["sheet"]
                new_name = arguments["new_name"]

                # Get sheet ID
                spreadsheet_data = (
                    sheets_service.spreadsheets()
                    .get(spreadsheetId=spreadsheet_id)
                    .execute()
                )
                sheet_id = None

                for s in spreadsheet_data["sheets"]:
                    if s["properties"]["title"] == sheet:
                        sheet_id = s["properties"]["sheetId"]
                        break

                if sheet_id is None:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": f"Sheet '{sheet}' not found"}, indent=2
                            ),
                        )
                    ]

                request_body = {
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": sheet_id, "title": new_name},
                                "fields": "title",
                            }
                        }
                    ]
                }

                result = (
                    sheets_service.spreadsheets()
                    .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
                    .execute()
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            if name == "get-multiple-sheet-data":
                queries = arguments["queries"]
                results = []

                for query in queries:
                    spreadsheet_id = extract_spreadsheet_id(query["spreadsheet_url"])
                    sheet = query["sheet"]
                    range_str = query["range"]

                    try:
                        full_range = f"{sheet}!{range_str}"
                        result = (
                            sheets_service.spreadsheets()
                            .values()
                            .get(spreadsheetId=spreadsheet_id, range=full_range)
                            .execute()
                        )

                        values = result.get("values", [])
                        results.append({**query, "data": values})
                    except Exception as e:
                        results.append({**query, "error": str(e)})

                return [
                    types.TextContent(type="text", text=json.dumps(results, indent=2))
                ]

            if name == "get-multiple-spreadsheet-summary":
                spreadsheet_urls = arguments["spreadsheet_urls"]
                rows_to_fetch = arguments.get("rows_to_fetch", 5)
                summaries = []

                for spreadsheet_url in spreadsheet_urls:
                    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
                    summary_data = {
                        "spreadsheet_url": spreadsheet_url,
                        "spreadsheet_id": spreadsheet_id,
                        "title": None,
                        "sheets": [],
                        "error": None,
                    }

                    try:
                        spreadsheet = (
                            sheets_service.spreadsheets()
                            .get(
                                spreadsheetId=spreadsheet_id,
                                fields="properties.title,sheets(properties(title,sheetId))",
                            )
                            .execute()
                        )

                        summary_data["title"] = spreadsheet.get("properties", {}).get(
                            "title", "Unknown Title"
                        )

                        sheet_summaries = []
                        for sheet in spreadsheet.get("sheets", []):
                            sheet_title = sheet.get("properties", {}).get("title")
                            sheet_id = sheet.get("properties", {}).get("sheetId")
                            sheet_summary = {
                                "title": sheet_title,
                                "sheet_id": sheet_id,
                                "headers": [],
                                "first_rows": [],
                                "error": None,
                            }

                            if sheet_title:
                                try:
                                    max_row = max(1, rows_to_fetch)
                                    range_to_get = f"{sheet_title}!A1:{max_row}"

                                    result = (
                                        sheets_service.spreadsheets()
                                        .values()
                                        .get(
                                            spreadsheetId=spreadsheet_id,
                                            range=range_to_get,
                                        )
                                        .execute()
                                    )

                                    values = result.get("values", [])

                                    if values:
                                        sheet_summary["headers"] = values[0]
                                        if len(values) > 1:
                                            sheet_summary["first_rows"] = values[
                                                1:max_row
                                            ]
                                    else:
                                        sheet_summary["headers"] = []
                                        sheet_summary["first_rows"] = []
                                except Exception as sheet_e:
                                    sheet_summary["error"] = (
                                        f"Error fetching data for sheet {sheet_title}: {sheet_e}"
                                    )
                            else:
                                sheet_summary["error"] = "Sheet title not found"

                            sheet_summaries.append(sheet_summary)

                        summary_data["sheets"] = sheet_summaries

                    except Exception as e:
                        summary_data["error"] = (
                            f"Error fetching spreadsheet {spreadsheet_id}: {e}"
                        )

                    summaries.append(summary_data)

                return [
                    types.TextContent(type="text", text=json.dumps(summaries, indent=2))
                ]

            if name == "list-spreadsheets":
                query = "mimeType='application/vnd.google-apps.spreadsheet'"

                results = (
                    drive_service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                        fields="files(id, name)",
                        orderBy="modifiedTime desc",
                    )
                    .execute()
                )

                spreadsheets = results.get("files", [])
                formatted_results = []

                for sheet in spreadsheets:
                    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet['id']}"
                    formatted_results.append(
                        {"id": sheet["id"], "title": sheet["name"], "url": sheet_url}
                    )

                return [
                    types.TextContent(
                        type="text", text=json.dumps(formatted_results, indent=2)
                    )
                ]

            if name == "share-spreadsheet":
                spreadsheet_id = arguments[
                    "spreadsheet_url"
                ]  # Changed from spreadsheet_id to spreadsheet_url
                recipients = arguments["recipients"]
                send_notification = arguments.get("send_notification", True)
                successes = []
                failures = []

                for recipient in recipients:
                    email_address = recipient.get("email_address")
                    role = recipient.get("role", "writer")

                    if not email_address:
                        failures.append(
                            {
                                "email_address": None,
                                "error": "Missing email_address in recipient entry.",
                            }
                        )
                        continue

                    if role not in ["reader", "commenter", "writer"]:
                        failures.append(
                            {
                                "email_address": email_address,
                                "error": f"Invalid role '{role}'. Must be 'reader', 'commenter', or 'writer'.",
                            }
                        )
                        continue

                    permission = {
                        "type": "user",
                        "role": role,
                        "emailAddress": email_address,
                    }

                    try:
                        result = (
                            drive_service.permissions()
                            .create(
                                fileId=spreadsheet_id,
                                body=permission,
                                sendNotificationEmail=send_notification,
                                fields="id",
                            )
                            .execute()
                        )
                        successes.append(
                            {
                                "email_address": email_address,
                                "role": role,
                                "permissionId": result.get("id"),
                            }
                        )
                    except Exception as e:
                        error_details = str(e)
                        if hasattr(e, "content"):
                            try:
                                error_content = json.loads(e.content)
                                error_details = error_content.get("error", {}).get(
                                    "message", error_details
                                )
                            except json.JSONDecodeError:
                                pass
                        failures.append(
                            {
                                "email_address": email_address,
                                "error": f"Failed to share: {error_details}",
                            }
                        )

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"successes": successes, "failures": failures}, indent=2
                        ),
                    )
                ]

            if name == "append-values":
                spreadsheet_id = arguments["spreadsheet_id"]
                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .append(
                        spreadsheetId=spreadsheet_id,
                        range=arguments["range"],
                        valueInputOption="RAW",
                        body={"values": arguments["values"]},
                    )
                    .execute()
                )
                updates = result.get("updates", {})
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "message": f"Appended {updates.get('updatedRows', '?')} rows.",
                                "result": result,
                            },
                            indent=2,
                        ),
                    )
                ]

            if name == "clear-values":
                spreadsheet_id = arguments["spreadsheet_id"]
                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=spreadsheet_id, range=arguments["range"], body={}
                    )
                    .execute()
                )
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "message": "Range cleared successfully.",
                                "result": result,
                            },
                            indent=2,
                        ),
                    )
                ]

            raise ValueError(f"Unknown tool: {name}")
        finally:
            sheets_service.close()
            drive_service.close()

    return server


server = create_server


# @profile
def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server

    Args:
        server_instance (Server): The server instance to configure.

    Returns:
        InitializationOptions: Initialization configuration for guMCP.
    """
    return InitializationOptions(
        server_name="gsheets-server",
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
