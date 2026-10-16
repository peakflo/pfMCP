"""Zendesk ticket tools backed by a Nango OAuth connection."""

import json
import logging
import os
from pathlib import Path

import httpx
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from src.auth.factory import create_auth_client
from src.utils.mcp_compat import NotificationOptions, Server

SERVICE_NAME = Path(__file__).parent.name
logger = logging.getLogger(__name__)


async def make_zendesk_request(
    method, path, user_id, api_key=None, params=None, data=None
):
    """Use Nango's proxy so it resolves the Zendesk account URL and OAuth token."""
    auth_client = create_auth_client(api_key=api_key)
    credentials = await auth_client.async_get_user_credentials(SERVICE_NAME, user_id)
    if not credentials or not credentials.get("access_token"):
        raise ValueError("Zendesk OAuth connection is missing or has no access token")

    secret = os.environ.get("NANGO_SECRET_KEY")
    if not secret:
        raise ValueError("NANGO_SECRET_KEY is required for Zendesk API requests")
    host = os.environ.get("NANGO_HOST", "https://api.nango.dev").rstrip("/")
    headers = {
        "Authorization": f"Bearer {secret}",
        "Provider-Config-Key": "zendesk",
        "Connection-Id": user_id,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{host}/proxy/api/v2/{path}",
            headers=headers,
            params=params,
            json=data,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ValueError(
            f"Zendesk API returned HTTP {response.status_code}: {response.text}"
        ) from error
    return response.json()


def _page_size(arguments):
    size = arguments.get("page_size", 25)
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 100:
        raise ValueError("page_size must be an integer between 1 and 100")
    return size


def _ticket_id(arguments):
    ticket_id = arguments.get("ticket_id")
    if isinstance(ticket_id, bool) or not isinstance(ticket_id, int) or ticket_id <= 0:
        raise ValueError("ticket_id must be a positive integer")
    return ticket_id


def create_server(user_id, api_key=None):
    server = Server("zendesk-server")
    server.user_id = user_id

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_tickets",
                description="List recent Zendesk tickets with cursor pagination",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
                        "after_cursor": {
                            "type": "string",
                            "description": "Cursor returned by the previous page",
                        },
                    },
                },
            ),
            Tool(
                name="get_ticket",
                description="Read a Zendesk ticket by ID",
                inputSchema={
                    "type": "object",
                    "properties": {"ticket_id": {"type": "integer", "minimum": 1}},
                    "required": ["ticket_id"],
                },
            ),
            Tool(
                name="search_tickets",
                description="Search Zendesk tickets using Zendesk search syntax; returns pagination details",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Ticket search terms, for example status:open",
                        },
                        "page": {"type": "integer", "minimum": 1, "maximum": 10},
                        "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
                        "sort_by": {
                            "type": "string",
                            "enum": ["created_at", "updated_at", "priority", "status"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="update_ticket",
                description="Update ticket fields or add a public reply or internal note",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "integer", "minimum": 1},
                        "subject": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["new", "open", "pending", "hold", "solved"],
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "normal", "high", "urgent"],
                        },
                        "assignee_id": {"type": "integer", "minimum": 1},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "comment": {"type": "string"},
                        "public": {
                            "type": "boolean",
                            "description": "Whether comment is a public reply (default true)",
                        },
                    },
                    "required": ["ticket_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        args = arguments or {}
        if name == "list_tickets":
            params = {"page[size]": _page_size(args)}
            if args.get("after_cursor"):
                params["page[after]"] = args["after_cursor"]
            result = await make_zendesk_request(
                "GET", "tickets.json", user_id, api_key, params=params
            )
            output = {
                "tickets": result.get("tickets", []),
                "next_cursor": (
                    result.get("meta", {}).get("after_cursor")
                    if result.get("meta", {}).get("has_more")
                    else None
                ),
                "has_more": result.get("meta", {}).get("has_more", False),
            }
        elif name == "get_ticket":
            ticket_id = _ticket_id(args)
            result = await make_zendesk_request(
                "GET", f"tickets/{ticket_id}.json", user_id, api_key
            )
            output = result.get("ticket", result)
        elif name == "search_tickets":
            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("query must be a non-empty string")
            page = args.get("page", 1)
            if (
                isinstance(page, bool)
                or not isinstance(page, int)
                or not 1 <= page <= 10
            ):
                raise ValueError("page must be an integer between 1 and 10")
            params = {
                "query": f"type:ticket {query.strip()}",
                "page": page,
                "per_page": _page_size(args),
            }
            for key in ("sort_by", "sort_order"):
                if key in args:
                    params[key] = args[key]
            result = await make_zendesk_request(
                "GET", "search.json", user_id, api_key, params=params
            )
            output = {
                "tickets": [
                    item
                    for item in result.get("results", [])
                    if item.get("result_type", item.get("type")) == "ticket"
                ],
                "count": result.get("count", 0),
                "next_page": result.get("next_page"),
            }
        elif name == "update_ticket":
            ticket_id = _ticket_id(args)
            fields = ("subject", "status", "priority", "assignee_id", "tags")
            ticket = {key: args[key] for key in fields if key in args}
            if "comment" in args:
                if not isinstance(args["comment"], str) or not args["comment"].strip():
                    raise ValueError("comment must be a non-empty string")
                ticket["comment"] = {
                    "body": args["comment"],
                    "public": args.get("public", True),
                }
            elif "public" in args:
                raise ValueError("public requires comment")
            if not ticket:
                raise ValueError("At least one ticket field or comment is required")
            result = await make_zendesk_request(
                "PUT",
                f"tickets/{ticket_id}.json",
                user_id,
                api_key,
                data={"ticket": ticket},
            )
            output = result.get("ticket", result)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(output))]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="zendesk-server",
        server_version="2.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(), experimental_capabilities={}
        ),
    )
