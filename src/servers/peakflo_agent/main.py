import json
import os
from pathlib import Path

import httpx
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from src.utils.mcp_compat import NotificationOptions, Server

SERVICE_NAME = Path(__file__).parent.name


def _base_url() -> str:
    configured = os.environ.get("PEAKFLO_AGENT_RUNTIME_BASE_URL") or os.environ.get(
        "PEAKFLO_API_BASE_URL"
    )
    if not configured:
        raise ValueError("PEAKFLO_AGENT_RUNTIME_BASE_URL is not configured")
    return configured.rstrip("/")


async def _runtime_request(
    session_token: str, method: str, path: str, payload: dict | None = None
) -> dict:
    if not session_token:
        raise ValueError("A signed Peakflo agent session token is required")
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            f"{_base_url()}{path}",
            headers={"Authorization": f"Bearer {session_token}"},
            json=payload,
            timeout=60.0,
        )
    response.raise_for_status()
    return response.json()


async def list_scoped_tools(session_token: str) -> list[Tool]:
    response = await _runtime_request(
        session_token, "GET", "/v1/autonomous-agent-session/tools"
    )
    return [
        Tool(
            name=item["name"],
            description=item["description"],
            inputSchema=item["inputSchema"],
        )
        for item in response.get("tools", [])
    ]


async def call_scoped_tool(
    session_token: str, name: str, arguments: dict | None
) -> dict:
    # The adapter forwards no tenant, role, permissions, document ID, or session ID.
    # The verified bearer token identifies the server-loaded scoped session.
    return await _runtime_request(
        session_token,
        "POST",
        f"/v1/autonomous-agent-session/tools/{name}",
        arguments or {},
    )


def create_server(user_id: str, api_key: str | None = None):
    server = Server(f"{SERVICE_NAME}-server")
    server.user_id = user_id
    server.session_token = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return await list_scoped_tools(server.session_token)

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        try:
            live_names = {
                tool.name for tool in await list_scoped_tools(server.session_token)
            }
            if name not in live_names:
                return [TextContent(type="text", text=f"Tool not allowed: {name}")]
            result = await call_scoped_tool(server.session_token, name, arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as error:
            return [TextContent(type="text", text=f"Peakflo agent tool error: {error}")]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name=f"{SERVICE_NAME}-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
