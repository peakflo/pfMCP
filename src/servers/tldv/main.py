import os
import sys
import logging
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
import aiohttp
from datetime import datetime

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.utils.tldv.util import get_credentials

SERVICE_NAME = Path(__file__).parent.name
BASE_URL = "https://pasta.tldv.io/v1alpha1"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


class TldvApiClient:
    """TLDV API Client for making authenticated requests"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = BASE_URL
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a request to the TLDV API with retry logic"""
        max_retries = 3
        retry_delay = 1.0
        max_retry_delay = 2.0

        for attempt in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}{endpoint}"

                    if params:
                        # Convert params to URL query string
                        query_params = []
                        for key, value in params.items():
                            if value is not None:
                                if isinstance(value, bool):
                                    query_params.append(f"{key}={str(value).lower()}")
                                else:
                                    query_params.append(f"{key}={value}")
                        if query_params:
                            url += "?" + "&".join(query_params)

                    async with session.request(
                        method=method, url=url, headers=self.headers, json=data
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.error(
                                f"API request failed: {response.status} - {error_text}"
                            )
                            raise Exception(
                                f"API request failed: {response.status} - {error_text}"
                            )

                        result = await response.json()
                        return result

            except Exception as e:
                if attempt == max_retries:
                    raise e

                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)}"
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        """Get a meeting by ID"""
        return await self.request(f"/meetings/{meeting_id}")

    async def get_meetings(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get a list of meetings with optional filtering"""
        return await self.request("/meetings", params=params)

    async def get_transcript(self, meeting_id: str) -> Dict[str, Any]:
        """Get the transcript for a specific meeting"""
        return await self.request(f"/meetings/{meeting_id}/transcript")

    async def get_highlights(self, meeting_id: str) -> Dict[str, Any]:
        """Get the highlights for a specific meeting"""
        return await self.request(f"/meetings/{meeting_id}/highlights")

    async def health_check(self) -> Dict[str, Any]:
        """Check the health status of the API"""
        return await self.request("/health")


async def get_tldv_client(user_id: str, api_key: Optional[str] = None) -> TldvApiClient:
    """Get authenticated TLDV API client"""
    api_key = await get_credentials(user_id, api_key)
    return TldvApiClient(api_key)


# Create server instance
server = Server(SERVICE_NAME)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
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
        types.Tool(
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
        types.Tool(
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
        types.Tool(
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
        types.Tool(
            name="health_check", description="Check the health status of the TLDV API"
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None, user_id: str, api_key: str | None = None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    try:
        client = await get_tldv_client(user_id, api_key)

        if name == "get_meeting":
            meeting_id = arguments.get("meeting_id")
            if not meeting_id:
                raise ValueError("meeting_id is required")

            result = await client.get_meeting(meeting_id)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_meetings":
            # Build query parameters
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

            result = await client.get_meetings(params)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_transcript":
            meeting_id = arguments.get("meeting_id")
            if not meeting_id:
                raise ValueError("meeting_id is required")

            result = await client.get_transcript(meeting_id)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_highlights":
            meeting_id = arguments.get("meeting_id")
            if not meeting_id:
                raise ValueError("meeting_id is required")

            result = await client.get_highlights(meeting_id)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "health_check":
            result = await client.health_check()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Error in tool {name}: {str(e)}")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available resources"""
    return []


@server.read_resource()
async def handle_read_resource(
    uri: str, user_id: str, api_key: str | None = None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Read a resource"""
    raise ValueError(f"Unknown resource: {uri}")


def create_server(user_id: str, api_key: str | None = None) -> Server:
    """Create a server instance for the given user and API key"""
    # The server instance is already created globally, but we need to return it
    # In a real implementation, you might want to create a new instance per user
    return server


def get_initialization_options() -> InitializationOptions:
    """Get initialization options for the server"""
    return InitializationOptions(
        server_name=SERVICE_NAME,
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={}
        ),
    )


if __name__ == "__main__":
    import asyncio

    async def main():
        # Check if auth argument is provided
        if len(sys.argv) > 1 and sys.argv[1] == "auth":
            if len(sys.argv) < 3:
                print("Usage: python main.py auth <user_id>")
                sys.exit(1)

            user_id = sys.argv[2]
            api_key = input("Enter your TLDV API key: ").strip()

            if not api_key:
                print("API key is required")
                sys.exit(1)

            # Save credentials
            auth_client = create_auth_client(api_key=api_key)
            auth_client.save_user_credentials(
                SERVICE_NAME, user_id, {"api_key": api_key}
            )
            print(f"Credentials saved for user {user_id}")
            return

        # Run the server
        await server.run()

    asyncio.run(main())
