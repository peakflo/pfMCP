import os
import sys
import logging
import json
from pathlib import Path
from typing import Any

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from src.utils.mcp_compat import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from notion_client import AsyncClient
from src.auth.factory import create_auth_client
from src.utils.notion.util import (
    authenticate_and_save_credentials,
    extract_page_id_from_url,
)

SERVICE_NAME = Path(__file__).parent.name
SCOPES = ["all"]  # Notion doesn't use granular OAuth scopes like Google
MAX_QUERY_PAGE_SIZE = 100
MAX_CREATE_PAGE_CHILDREN = 100

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def resolve_page_id(page_value: Any) -> str:
    """Resolve a Notion page ID from either a raw ID or a Notion URL."""
    if not isinstance(page_value, str) or not page_value.strip():
        raise ValueError("page must be a non-empty Notion page ID or URL")

    normalized = page_value.strip()
    if (
        "notion.so" in normalized
        or "notion.site" in normalized
        or normalized.startswith(("http://", "https://"))
    ):
        return extract_page_id_from_url(normalized)

    return normalized


def _build_query_database_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and build keyword arguments for ``notion.databases.query``."""
    database_id = arguments.get("database_id")
    if not isinstance(database_id, str) or not database_id.strip():
        raise ValueError("database_id must be a non-empty string")

    query_kwargs: dict[str, Any] = {"database_id": database_id.strip()}

    if "filter" in arguments and arguments["filter"] is not None:
        filter_arg = arguments["filter"]
        if not isinstance(filter_arg, dict) or not filter_arg:
            raise ValueError("filter must be a non-empty object")
        query_kwargs["filter"] = filter_arg

    if "sorts" in arguments and arguments["sorts"] is not None:
        sorts_arg = arguments["sorts"]
        if not isinstance(sorts_arg, list) or not all(
            isinstance(item, dict) and bool(item) for item in sorts_arg
        ):
            raise ValueError("sorts must be a list of non-empty sort objects")
        if sorts_arg:
            query_kwargs["sorts"] = sorts_arg

    if "page_size" in arguments and arguments["page_size"] is not None:
        page_size = arguments["page_size"]
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size < 1
            or page_size > MAX_QUERY_PAGE_SIZE
        ):
            raise ValueError(
                f"page_size must be an integer between 1 and {MAX_QUERY_PAGE_SIZE}"
            )
        query_kwargs["page_size"] = page_size

    if "start_cursor" in arguments and arguments["start_cursor"] is not None:
        start_cursor = arguments["start_cursor"]
        if not isinstance(start_cursor, str) or not start_cursor.strip():
            raise ValueError("start_cursor must be a non-empty string")
        query_kwargs["start_cursor"] = start_cursor.strip()

    return query_kwargs


def _format_query_database_result(result: Any) -> Any:
    """Ensure ``query_database`` responses consistently expose pagination fields."""
    if not isinstance(result, dict):
        return result
    return {
        **result,
        "results": result.get("results", []),
        "has_more": bool(result.get("has_more", False)),
        "next_cursor": result.get("next_cursor"),
    }


def _build_create_page_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and build keyword arguments for ``notion.pages.create``."""
    database_id = arguments.get("database_id")
    if not isinstance(database_id, str) or not database_id.strip():
        raise ValueError("database_id must be a non-empty string")

    properties = arguments.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("properties must be an object")

    create_kwargs: dict[str, Any] = {
        "parent": {"database_id": database_id.strip()},
        "properties": properties,
    }

    if "children" in arguments and arguments["children"] is not None:
        children = arguments["children"]
        if not isinstance(children, list) or not all(
            isinstance(block, dict) and bool(block) for block in children
        ):
            raise ValueError("children must be a list of non-empty block objects")
        if len(children) > MAX_CREATE_PAGE_CHILDREN:
            raise ValueError(
                f"children cannot exceed {MAX_CREATE_PAGE_CHILDREN} blocks; "
                "use append_blocks for additional blocks"
            )
        if children:
            create_kwargs["children"] = children

    return create_kwargs


def _build_update_page_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and build keyword arguments for ``notion.pages.update``."""
    page_id = resolve_page_id(arguments.get("page"))

    update_kwargs: dict[str, Any] = {"page_id": page_id}

    if "properties" in arguments and arguments["properties"] is not None:
        properties = arguments["properties"]
        if not isinstance(properties, dict) or not properties:
            raise ValueError("properties must be a non-empty object")
        update_kwargs["properties"] = properties

    if "archived" in arguments and arguments["archived"] is not None:
        archived = arguments["archived"]
        if not isinstance(archived, bool):
            raise ValueError("archived must be a boolean")
        update_kwargs["archived"] = archived

    if "icon" in arguments and arguments["icon"] is not None:
        icon = arguments["icon"]
        if not isinstance(icon, dict) or not icon:
            raise ValueError("icon must be a non-empty object")
        update_kwargs["icon"] = icon

    if "cover" in arguments and arguments["cover"] is not None:
        cover = arguments["cover"]
        if not isinstance(cover, dict) or not cover:
            raise ValueError("cover must be a non-empty object")
        update_kwargs["cover"] = cover

    if len(update_kwargs) == 1:
        raise ValueError(
            "At least one of 'properties', 'archived', 'icon', or 'cover' must be provided"
        )

    return update_kwargs


async def get_credentials(user_id, api_key=None):
    """
    Retrieves the OAuth access token for a specific Notion user.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key passed during server creation.

    Returns:
        str: The access token to authenticate with the Notion API.

    Raises:
        ValueError: If credentials are missing or invalid.
    """
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    def handle_missing():
        err = f"Notion credentials not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            err += " Please run with 'auth' argument first."
        logger.error(err)
        raise ValueError(err)

    if not credentials_data:
        handle_missing()

    token = credentials_data.get("access_token") or credentials_data.get("api_key")
    if token:
        return token
    handle_missing()


async def create_notion_client(user_id, api_key=None):
    """
    Creates an authorized Notion AsyncClient instance.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key.

    Returns:
        AsyncClient: An authenticated Notion client object.
    """
    token = await get_credentials(user_id, api_key)
    return AsyncClient(auth=token)


def create_server(user_id, api_key=None):
    """
    Initializes and configures a Notion MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.

    Returns:
        Server: Configured server instance with all Notion tools registered.
    """
    server = Server("notion-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        Lists all available tools for interacting with the Notion API.

        Returns:
            list[types.Tool]: A list of tool metadata with schema definitions.
        """
        logger.info(f"Listing tools for user: {user_id}")
        return [
            types.Tool(
                name="list_all_users",
                description="List all users in Notion",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="search_pages",
                description="Search pages by text in Notion",
                inputSchema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="list_databases",
                description="List all databases in Notion",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="query_database",
                description="Query a Notion database with optional filter, sorts, and pagination",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "database_id": {
                            "type": "string",
                            "description": "The ID of the Notion database to query",
                        },
                        "filter": {
                            "type": "object",
                            "description": "Optional Notion database filter object",
                        },
                        "sorts": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Optional list of Notion sort objects",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_QUERY_PAGE_SIZE,
                            "description": "Optional number of results per page (1-100)",
                        },
                        "start_cursor": {
                            "type": "string",
                            "description": "Optional pagination cursor returned as next_cursor from a previous query",
                        },
                    },
                    "required": ["database_id"],
                },
            ),
            types.Tool(
                name="get_page",
                description="Retrieve a page by ID or URL in Notion",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "string",
                            "description": "The page ID or Notion page URL",
                        }
                    },
                    "required": ["page"],
                },
            ),
            types.Tool(
                name="create_page",
                description="Create a new page in a database in Notion, optionally with initial body blocks",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "database_id": {
                            "type": "string",
                            "description": "The ID of the parent Notion database",
                        },
                        "properties": {
                            "type": "object",
                            "description": "Notion page property values matching the database schema",
                        },
                        "children": {
                            "type": "array",
                            "items": {"type": "object"},
                            "maxItems": MAX_CREATE_PAGE_CHILDREN,
                            "description": "Optional list of Notion block objects (e.g., paragraphs, headings, bookmark links) to add as initial page content (up to 100 blocks)",
                        },
                    },
                    "required": ["database_id", "properties"],
                },
            ),
            types.Tool(
                name="update_page",
                description="Update a page's properties, archived status, icon, or cover in Notion",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "string",
                            "description": "The page ID or Notion page URL to update",
                        },
                        "properties": {
                            "type": "object",
                            "description": "Notion page property values to update",
                        },
                        "archived": {
                            "type": "boolean",
                            "description": "Set to true to archive (trash) the page, or false to restore it",
                        },
                        "icon": {
                            "type": "object",
                            "description": "Notion page icon object (e.g., emoji or external URL)",
                        },
                        "cover": {
                            "type": "object",
                            "description": "Notion page cover object (e.g., external URL)",
                        },
                    },
                    "required": ["page"],
                },
            ),
            types.Tool(
                name="append_blocks",
                description="Append content blocks to a page or block in Notion",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "children": {"type": "array"},
                    },
                    "required": ["block_id", "children"],
                },
            ),
            types.Tool(
                name="get_block_children",
                description="List content blocks of a page or block in Notion",
                inputSchema={
                    "type": "object",
                    "properties": {"block_id": {"type": "string"}},
                    "required": ["block_id"],
                },
            ),
            types.Tool(
                name="comment_on_page",
                description="Add a comment to a page in Notion (top-level page comment)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "string",
                            "description": "The page ID or Notion page URL to comment on",
                        },
                        "comment": {
                            "type": "string",
                            "description": "The comment text to add (plain text or markdown)",
                        },
                    },
                    "required": ["page", "comment"],
                },
            ),
            types.Tool(
                name="comment_on_block",
                description="Add a comment to a specific block in Notion (inline comment on that block)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "block_id": {
                            "type": "string",
                            "description": "The block ID to attach the comment to",
                        },
                        "comment": {
                            "type": "string",
                            "description": "The comment text to add (plain text or markdown)",
                        },
                    },
                    "required": ["block_id", "comment"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """
        Dispatches a tool call to the corresponding Notion API method.

        Args:
            name (str): The tool name to execute.
            arguments (dict | None): Arguments to pass to the tool.

        Returns:
            list[types.TextContent]: The JSON-formatted result of the API call.

        Raises:
            ValueError: If an unknown tool name is provided.
        """
        logger.info(f"User {user_id} calling tool: {name} with args: {arguments}")

        if arguments is None:
            arguments = {}

        try:
            if name == "list_all_users":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.users.list()
            elif name == "search_pages":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.search(query=arguments["query"])
            elif name == "list_databases":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.search(
                    filter={"property": "object", "value": "database"}
                )
            elif name == "query_database":
                query_kwargs = _build_query_database_kwargs(arguments)
                notion = await create_notion_client(server.user_id, server.api_key)
                raw_result = await notion.databases.query(**query_kwargs)
                result = _format_query_database_result(raw_result)
            elif name == "get_page":
                page_id = resolve_page_id(arguments["page"])
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.pages.retrieve(page_id=page_id)
            elif name == "create_page":
                create_kwargs = _build_create_page_kwargs(arguments)
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.pages.create(**create_kwargs)
            elif name == "update_page":
                update_kwargs = _build_update_page_kwargs(arguments)
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.pages.update(**update_kwargs)
            elif name == "append_blocks":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.blocks.children.append(
                    block_id=arguments["block_id"], children=arguments["children"]
                )
            elif name == "get_block_children":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.blocks.children.list(
                    block_id=arguments["block_id"]
                )
            elif name == "comment_on_page":
                page_id = resolve_page_id(arguments["page"])
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.comments.create(
                    parent={"page_id": page_id},
                    rich_text=[
                        {"type": "text", "text": {"content": arguments["comment"]}}
                    ],
                )
            elif name == "comment_on_block":
                notion = await create_notion_client(server.user_id, server.api_key)
                result = await notion.comments.create(
                    parent={"block_id": arguments["block_id"]},
                    rich_text=[
                        {"type": "text", "text": {"content": arguments["comment"]}}
                    ],
                )
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error calling Notion API: {e}")
            raise

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """
    Provides initialization options required for registering the server.

    Args:
        server_instance (Server): The guMCP server instance.

    Returns:
        InitializationOptions: The initialization configuration block.
    """
    return InitializationOptions(
        server_name="notion-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
