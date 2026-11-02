import os
import sys
from typing import Optional, Iterable
import json

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path
import httpx

from mcp.types import (
    Resource,
    TextContent,
    Tool,
    ImageContent,
    EmbeddedResource,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from src.utils.mcp_compat import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.utils.zendesk.util import (
    authenticate_and_save_credentials,
    get_credentials,
    get_service_config,
)
from src.auth.constants import SERVICE_NAME_MAP
from src.auth.factory import create_auth_client

SERVICE_NAME = Path(__file__).parent.name
SCOPES = [
    "read",
    "write",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def ticket_url(ticket, subdomain):
    if subdomain:
        return f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}"
    return ticket.get("url", "")


async def make_zendesk_request(
    method,
    path,
    access_token=None,
    subdomain=None,
    data=None,
    params=None,
    connection_id=None,
):
    """Make a request to the Zendesk API"""
    if not access_token:
        raise ValueError("Zendesk access token is required")
    if subdomain:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        url = f"https://{subdomain}.zendesk.com/api/v2/{path}"
    elif connection_id:
        secret = os.environ.get("NANGO_SECRET_KEY")
        if not secret:
            raise ValueError("NANGO_SECRET_KEY is required for Zendesk proxy requests")
        headers = {
            "Authorization": f"Bearer {secret}",
            "Provider-Config-Key": SERVICE_NAME_MAP[SERVICE_NAME]["nango_service_name"],
            "Connection-Id": connection_id,
        }
        url = f"{os.environ.get('NANGO_HOST', 'https://api.nango.dev').rstrip('/')}/proxy/api/v2/{path}"
    else:
        raise ValueError("Zendesk subdomain or Nango connection is required")

    async with httpx.AsyncClient(timeout=30) as client:
        if method.lower() == "get":
            response = await client.get(url, headers=headers, params=params)
        elif method.lower() == "post":
            response = await client.post(url, headers=headers, json=data)
        elif method.lower() == "put":
            response = await client.put(url, headers=headers, json=data)
        elif method.lower() == "delete":
            response = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code >= 400:
            raise ValueError(
                f"Zendesk API error: {response.status_code} - {response.text}"
            )

        return response.json()


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("zendesk-server")

    server.user_id = user_id

    async def get_zendesk_client():
        """Get Zendesk access token and subdomain for the current user"""
        if os.environ.get("ENVIRONMENT", "local").lower() == "nango":
            auth_client = create_auth_client(api_key=api_key)
            if hasattr(auth_client, "async_get_user_credentials"):
                credentials = await auth_client.async_get_user_credentials(
                    SERVICE_NAME, user_id
                )
            else:
                credentials = auth_client.get_user_credentials(SERVICE_NAME, user_id)
            if not credentials or not credentials.get("access_token"):
                raise ValueError(
                    "Zendesk OAuth connection is missing or has no access token"
                )
            # Nango's proxy resolves the account-specific Zendesk subdomain.
            return credentials["access_token"], None

        # Get access token
        access_token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)

        # Get service config (contains subdomain)
        config = await get_service_config(user_id, SERVICE_NAME, api_key=api_key)
        subdomain = config.get("custom_subdomain", "")

        return access_token, subdomain

    async def request_zendesk(
        method, path, access_token, subdomain, data=None, params=None
    ):
        return await make_zendesk_request(
            method,
            path,
            access_token,
            subdomain,
            data=data,
            params=params,
            connection_id=user_id if subdomain is None else None,
        )

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List resources from Zendesk"""
        logger.info(
            f"Listing resources for user: {server.user_id} with cursor: {cursor}"
        )

        access_token, subdomain = await get_zendesk_client()

        resources = []

        # Add ticket views as resources
        views_params = {}
        if cursor:
            views_params["page"] = cursor

        views_data = await request_zendesk(
            "get", "views.json", access_token, subdomain, params=views_params
        )

        for view in views_data.get("views", []):
            resources.append(
                Resource(
                    uri=f"zendesk://view/{view['id']}",
                    mimeType="application/json",
                    name=f"View: {view['title']}",
                    description=f"Zendesk ticket view: {view['title']}",
                )
            )

        return resources

    @server.read_resource()
    async def handle_read_resource(uri: str) -> Iterable[ReadResourceContents]:
        """Read a resource from Zendesk by URI"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        access_token, subdomain = await get_zendesk_client()

        uri_str = str(uri)

        if uri_str.startswith("zendesk://view/"):
            # Handle view resource
            view_id = uri_str.replace("zendesk://view/", "")

            view_data = await request_zendesk(
                "get", f"views/{view_id}.json", access_token, subdomain
            )

            # Get tickets from this view
            view_tickets = await request_zendesk(
                "get", f"views/{view_id}/tickets.json", access_token, subdomain
            )

            # Combine view data with tickets
            combined_data = {
                "view": view_data.get("view", {}),
                "tickets": view_tickets.get("tickets", []),
            }

            formatted_content = json.dumps(combined_data, indent=2)
            return [
                ReadResourceContents(
                    content=formatted_content, mime_type="application/json"
                )
            ]

        raise ValueError(f"Unsupported resource URI: {uri_str}")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools for Zendesk"""
        logger.info(f"Listing tools for user: {server.user_id}")
        return [
            Tool(
                name="list_tickets",
                description="List recent Zendesk tickets with cursor pagination",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
                        "after_cursor": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="get_ticket",
                description="Read a Zendesk ticket by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "integer", "minimum": 1},
                    },
                    "required": ["ticket_id"],
                },
            ),
            Tool(
                name="search_tickets",
                description="Search for tickets in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for tickets",
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Field to sort by (created_at, updated_at, priority, status)",
                        },
                        "sort_order": {
                            "type": "string",
                            "description": "Sort order (asc, desc)",
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "Number of results per page (max 100)",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number (1-10)",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="create_ticket",
                description="Create a new ticket in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Subject of the ticket",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Initial comment/description for the ticket",
                        },
                        "priority": {
                            "type": "string",
                            "description": "Priority (low, normal, high, urgent)",
                        },
                        "type": {
                            "type": "string",
                            "description": "Type (problem, incident, question, task)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags to apply to the ticket",
                        },
                    },
                    "required": ["subject", "comment"],
                },
            ),
            Tool(
                name="update_ticket",
                description="Update an existing ticket in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "integer",
                            "description": "ID of the ticket to update",
                        },
                        "subject": {
                            "type": "string",
                            "description": "New subject (optional)",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Comment to add (optional)",
                        },
                        "status": {
                            "type": "string",
                            "description": "New status (new, open, pending, hold, solved, closed)",
                        },
                        "priority": {
                            "type": "string",
                            "description": "New priority (low, normal, high, urgent)",
                        },
                        "assignee_id": {
                            "type": "integer",
                            "description": "ID of agent to assign (optional)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags to replace on the ticket (optional)",
                        },
                    },
                    "required": ["ticket_id"],
                },
            ),
            Tool(
                name="add_comment",
                description="Add a comment to an existing ticket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "integer",
                            "description": "ID of the ticket to comment on",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Comment text to add",
                        },
                        "public": {
                            "type": "boolean",
                            "description": "Whether the comment is public or an internal note",
                        },
                    },
                    "required": ["ticket_id", "comment"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool execution requests for Zendesk"""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        access_token, subdomain = await get_zendesk_client()

        if name == "list_tickets":
            page_size = (arguments or {}).get("page_size", 25)
            if (
                isinstance(page_size, bool)
                or not isinstance(page_size, int)
                or not 1 <= page_size <= 100
            ):
                raise ValueError("page_size must be an integer between 1 and 100")
            params = {"page[size]": page_size}
            if arguments and arguments.get("after_cursor"):
                params["page[after]"] = arguments["after_cursor"]
            result = await request_zendesk(
                "get", "tickets.json", access_token, subdomain, params=params
            )
            meta = result.get("meta", {})
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "tickets": result.get("tickets", []),
                            "has_more": meta.get("has_more", False),
                            "next_cursor": (
                                meta.get("after_cursor")
                                if meta.get("has_more")
                                else None
                            ),
                        }
                    ),
                )
            ]

        elif name == "get_ticket":
            ticket_id = (arguments or {}).get("ticket_id")
            if (
                isinstance(ticket_id, bool)
                or not isinstance(ticket_id, int)
                or ticket_id <= 0
            ):
                raise ValueError("ticket_id must be a positive integer")
            result = await request_zendesk(
                "get", f"tickets/{ticket_id}.json", access_token, subdomain
            )
            return [
                TextContent(type="text", text=json.dumps(result.get("ticket", result)))
            ]

        elif name == "search_tickets":
            if not arguments or "query" not in arguments:
                raise ValueError("Missing query parameter")

            search_query = arguments["query"]
            if not isinstance(search_query, str) or not search_query.strip():
                raise ValueError("query must be a non-empty string")
            page = arguments.get("page", 1)
            if (
                isinstance(page, bool)
                or not isinstance(page, int)
                or not 1 <= page <= 10
            ):
                raise ValueError("page must be an integer between 1 and 10")

            params = {
                "query": f"type:ticket {search_query.strip()}",
                "sort_by": arguments.get("sort_by", "created_at"),
                "sort_order": arguments.get("sort_order", "desc"),
                "per_page": arguments.get("per_page", 10),
                "page": page,
            }

            try:
                result = await request_zendesk(
                    "get", "search.json", access_token, subdomain, params=params
                )
                results = result.get("results", [])

                # Filter to just tickets
                tickets = [
                    r
                    for r in results
                    if r.get("result_type", r.get("type")) == "ticket"
                ]

                if not tickets:
                    return [
                        TextContent(
                            type="text", text="No tickets found matching your query."
                        )
                    ]

                ticket_list = []
                for ticket in tickets:
                    status = ticket.get("status", "unknown")
                    priority = ticket.get("priority", "normal")

                    ticket_list.append(
                        f"Ticket #{ticket['id']}: {ticket['subject']}\n"
                        f"  Status: {status}\n"
                        f"  Priority: {priority}\n"
                        f"  Created: {ticket.get('created_at')}\n"
                        f"  Updated: {ticket.get('updated_at')}"
                    )

                formatted_result = "\n\n".join(ticket_list)
                return [
                    TextContent(
                        type="text",
                        text=f"Found {len(tickets)} tickets:\n\n{formatted_result}\n\nNext page: {result.get('next_page')}",
                    )
                ]

            except Exception as e:
                logger.error(f"Error searching tickets: {str(e)}")
                return [
                    TextContent(type="text", text=f"Error searching tickets: {str(e)}")
                ]

        elif name == "create_ticket":
            required_fields = ["subject", "comment"]
            for field in required_fields:
                if not arguments or field not in arguments:
                    raise ValueError(f"Missing required parameter: {field}")

            ticket_data = {
                "ticket": {
                    "subject": arguments["subject"],
                    "comment": {"body": arguments["comment"]},
                }
            }

            # Add optional fields
            if "priority" in arguments:
                ticket_data["ticket"]["priority"] = arguments["priority"]
            if "type" in arguments:
                ticket_data["ticket"]["type"] = arguments["type"]
            if "tags" in arguments:
                ticket_data["ticket"]["tags"] = arguments["tags"]

            try:
                result = await request_zendesk(
                    "post", "tickets.json", access_token, subdomain, data=ticket_data
                )
                ticket = result.get("ticket", {})

                if ticket:
                    return [
                        TextContent(
                            type="text",
                            text=f"Ticket created successfully!\n\n"
                            f"Ticket ID: {ticket.get('id')}\n"
                            f"Subject: {ticket.get('subject')}\n"
                            f"Status: {ticket.get('status')}\n"
                            f"URL: {ticket_url(ticket, subdomain)}",
                        )
                    ]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Failed to create ticket: {result}",
                        )
                    ]

            except Exception as e:
                logger.error(f"Error creating ticket: {str(e)}")
                return [
                    TextContent(type="text", text=f"Error creating ticket: {str(e)}")
                ]

        elif name == "update_ticket":
            if not arguments or "ticket_id" not in arguments:
                raise ValueError("Missing required parameter: ticket_id")

            ticket_id = arguments["ticket_id"]

            # Start with an empty ticket structure
            ticket_data = {"ticket": {}}

            # Add fields that are present
            if "subject" in arguments:
                ticket_data["ticket"]["subject"] = arguments["subject"]
            if "status" in arguments:
                ticket_data["ticket"]["status"] = arguments["status"]
            if "priority" in arguments:
                ticket_data["ticket"]["priority"] = arguments["priority"]
            if "assignee_id" in arguments:
                ticket_data["ticket"]["assignee_id"] = arguments["assignee_id"]
            if "tags" in arguments:
                ticket_data["ticket"]["tags"] = arguments["tags"]
            if "comment" in arguments:
                ticket_data["ticket"]["comment"] = {"body": arguments["comment"]}

            if not ticket_data["ticket"]:
                raise ValueError("At least one field to update must be provided")

            try:
                result = await request_zendesk(
                    "put",
                    f"tickets/{ticket_id}.json",
                    access_token,
                    subdomain,
                    data=ticket_data,
                )

                ticket = result.get("ticket", {})

                if ticket:
                    return [
                        TextContent(
                            type="text",
                            text=f"Ticket updated successfully!\n\n"
                            f"Ticket ID: {ticket.get('id')}\n"
                            f"Subject: {ticket.get('subject')}\n"
                            f"Status: {ticket.get('status')}\n"
                            f"URL: {ticket_url(ticket, subdomain)}",
                        )
                    ]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Failed to update ticket: {result}",
                        )
                    ]

            except Exception as e:
                logger.error(f"Error updating ticket: {str(e)}")
                return [
                    TextContent(type="text", text=f"Error updating ticket: {str(e)}")
                ]

        elif name == "add_comment":
            required_fields = ["ticket_id", "comment"]
            for field in required_fields:
                if not arguments or field not in arguments:
                    raise ValueError(f"Missing required parameter: {field}")

            ticket_id = arguments["ticket_id"]
            comment_text = arguments["comment"]
            is_public = arguments.get("public", True)

            ticket_data = {
                "ticket": {"comment": {"body": comment_text, "public": is_public}}
            }

            try:
                result = await request_zendesk(
                    "put",
                    f"tickets/{ticket_id}.json",
                    access_token,
                    subdomain,
                    data=ticket_data,
                )

                ticket = result.get("ticket", {})

                if ticket:
                    comment_type = "public comment" if is_public else "internal note"
                    return [
                        TextContent(
                            type="text",
                            text=f"Added {comment_type} to ticket successfully!\n\n"
                            f"Ticket ID: {ticket.get('id')}\n"
                            f"Subject: {ticket.get('subject')}\n"
                            f"URL: {ticket_url(ticket, subdomain)}",
                        )
                    ]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Failed to add comment: {result}",
                        )
                    ]

            except Exception as e:
                logger.error(f"Error adding comment: {str(e)}")
                return [
                    TextContent(type="text", text=f"Error adding comment: {str(e)}")
                ]

        raise ValueError(f"Unknown tool: {name}")

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="zendesk-server",
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
