import os
import sys
from typing import Optional, Iterable

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path

import aiohttp
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

from src.utils.tldv.util import authenticate_and_save_credentials, get_credentials

SERVICE_NAME = Path(__file__).parent.name
BASE_URL = "https://pasta.tldv.io/v1alpha1"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def create_tldv_client(user_id, api_key=None):
    """
    Create a new TLDV client instance using the stored API credentials.

    Args:
        user_id (str): The user ID associated with the credentials.
        api_key (str, optional): Optional override for authentication.

    Returns:
        dict: TLDV API client configuration with credentials initialized.
    """
    token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return {
        "api_key": token,
        "base_url": BASE_URL,
        "headers": {
            "x-api-key": token,
            "Content-Type": "application/json",
        },
    }


def create_server(user_id, api_key=None):
    """
    Initialize and configure the TLDV MCP server.

    Args:
        user_id (str): The user ID associated with the current session.
        api_key (str, optional): Optional API key override.

    Returns:
        Server: Configured MCP server instance with registered tools.
    """
    server = Server("tldv-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """
        Return a list of available TLDV tools.

        Returns:
            list[Tool]: List of tool definitions supported by this server.
        """
        return [
            Tool(
                name="get_meeting",
                description="Retrieve a meeting by its ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "meeting_id": {
                            "type": "string",
                            "description": "The unique identifier of the meeting",
                        }
                    },
                    "required": ["meeting_id"],
                },
            ),
            Tool(
                name="get_meetings",
                description="Retrieve a list of meetings with optional filtering",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to filter meetings",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination",
                            "minimum": 1,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results per page",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 50,
                        },
                        "from": {
                            "type": "string",
                            "description": "Start date for filtering (ISO 8601 format)",
                        },
                        "to": {
                            "type": "string",
                            "description": "End date for filtering (ISO 8601 format)",
                        },
                        "onlyParticipated": {
                            "type": "boolean",
                            "description": "Only return meetings where the user participated",
                        },
                        "meetingType": {
                            "type": "string",
                            "enum": ["internal", "external"],
                            "description": "Filter meetings by type (internal/external)",
                        },
                    },
                },
            ),
            Tool(
                name="get_transcript",
                description="Retrieve the transcript for a specific meeting",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "meeting_id": {
                            "type": "string",
                            "description": "The unique identifier of the meeting",
                        }
                    },
                    "required": ["meeting_id"],
                },
            ),
            Tool(
                name="get_highlights",
                description="Retrieve the highlights for a specific meeting",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "meeting_id": {
                            "type": "string",
                            "description": "The unique identifier of the meeting",
                        }
                    },
                    "required": ["meeting_id"],
                },
            ),
            Tool(
                name="health_check",
                description="Check the health status of the TLDV API",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """
        Handle TLDV tool invocation from the MCP system.

        Args:
            name (str): The name of the tool being called.
            arguments (dict | None): Parameters passed to the tool.

        Returns:
            list[Union[TextContent, ImageContent, EmbeddedResource]]:
                Output content from tool execution.
        """
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        if arguments is None:
            arguments = {}

        client_config = await create_tldv_client(server.user_id, api_key=server.api_key)

        try:
            async with aiohttp.ClientSession() as session:
                if name == "get_meeting":
                    meeting_id = arguments.get("meeting_id")
                    if not meeting_id:
                        raise ValueError("meeting_id is required")

                    url = f"{client_config['base_url']}/meetings/{meeting_id}"
                    async with session.get(
                        url, headers=client_config["headers"]
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )
                        result = await response.json()

                elif name == "get_meetings":
                    url = f"{client_config['base_url']}/meetings"
                    params = {}
                    if arguments.get("query"):
                        params["query"] = arguments["query"]
                    if arguments.get("page"):
                        params["page"] = arguments["page"]
                    if arguments.get("limit"):
                        params["limit"] = arguments["limit"]
                    if arguments.get("from"):
                        params["from"] = arguments["from"]
                    if arguments.get("to"):
                        params["to"] = arguments["to"]
                    if arguments.get("onlyParticipated") is not None:
                        params["onlyParticipated"] = arguments["onlyParticipated"]
                    if arguments.get("meetingType"):
                        params["meetingType"] = arguments["meetingType"]

                    async with session.get(
                        url, headers=client_config["headers"], params=params
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )
                        result = await response.json()

                elif name == "get_transcript":
                    meeting_id = arguments.get("meeting_id")
                    if not meeting_id:
                        raise ValueError("meeting_id is required")

                    url = (
                        f"{client_config['base_url']}/meetings/{meeting_id}/transcript"
                    )
                    async with session.get(
                        url, headers=client_config["headers"]
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )
                        result = await response.json()

                elif name == "get_highlights":
                    meeting_id = arguments.get("meeting_id")
                    if not meeting_id:
                        raise ValueError("meeting_id is required")

                    url = (
                        f"{client_config['base_url']}/meetings/{meeting_id}/highlights"
                    )
                    async with session.get(
                        url, headers=client_config["headers"]
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )
                        result = await response.json()

                elif name == "health_check":
                    url = f"{client_config['base_url']}/health"
                    async with session.get(
                        url, headers=client_config["headers"]
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )
                        result = await response.json()

                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]

        except Exception as e:
            logger.error(f"TLDV API error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """
    Define the initialization options for the TLDV MCP server.

    Args:
        server_instance (Server): The server instance to describe.

    Returns:
        InitializationOptions: MCP-compatible initialization configuration.
    """
    return InitializationOptions(
        server_name="tldv-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_credentials(user_id, SERVICE_NAME, [])
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
