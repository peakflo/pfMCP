import os
import sys
from typing import Optional, Iterable

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
import json
from datetime import datetime
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

from src.utils.slack.util import authenticate_and_save_credentials, get_credentials

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SERVICE_NAME = Path(__file__).parent.name

# Footer appended to all outgoing messages for transparency.
# Since messages are posted as the authenticated user (no bot badge),
# this footer makes it clear the message was sent by an AI agent.
SENT_FROM_FOOTER = "\n\n_Sent from <https://peakflo.co/20x-agent-orchestrator|20x>_"

# User-level OAuth scopes required for posting as the user.
# These are requested as user_scopes in the Nango OAuth flow (xoxp- token).
SCOPES = [
    "chat:write",
    "channels:read",
    "channels:history",
    "groups:read",
    "groups:history",
    "reactions:write",
    "files:read",
    "files:write",
    "im:read",
    "users:read",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def append_footer(text: str) -> str:
    """Append the 'Sent from 20x' footer to a message for transparency.

    Since messages posted with a user token appear as if the user typed them,
    this footer distinguishes AI-generated content from manually typed messages.
    """
    return text + SENT_FROM_FOOTER


async def create_slack_client(user_id, api_key=None):
    """Create a new Slack client instance using a user token (xoxp-).

    Unlike the bot-based slack server which uses xoxb- tokens, this server
    uses user-level OAuth tokens so that messages are posted as the
    authenticated user (their display name, avatar, no bot badge).
    """
    token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return WebClient(token=token)


async def enrich_message_with_user_info(slack_client, message):
    """Add user info to the message"""
    user_id = message.get("user", "Unknown")

    if user_id != "Unknown":
        try:
            user_info = slack_client.users_info(user=user_id)
            if user_info["ok"]:
                user_data = user_info["user"]
                message["user_name"] = user_data.get("real_name") or user_data.get(
                    "name", "Unknown"
                )
                message["user_profile"] = user_data.get("profile", {})
        except SlackApiError:
            message["user_name"] = "Unknown"

    return message


async def get_channel_id(slack_client, server, channel_name):
    """Helper function to get channel ID from channel name with pagination support"""
    if not hasattr(server, "channel_name_to_id_map"):
        server.channel_name_to_id_map = {}

    if channel_name in server.channel_name_to_id_map:
        return server.channel_name_to_id_map[channel_name]

    cursor = None
    while True:
        pagination_params = {
            "types": "public_channel,private_channel",
            "limit": 200,
        }
        if cursor:
            pagination_params["cursor"] = cursor

        response = slack_client.conversations_list(**pagination_params)

        for ch in response["channels"]:
            server.channel_name_to_id_map[ch["name"]] = ch["id"]
            if ch["name"] == channel_name:
                return ch["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return None


async def get_user_id(slack_client, server, user_name):
    """Helper function to get user ID from username with pagination support"""
    if not hasattr(server, "user_name_to_id_map"):
        server.user_name_to_id_map = {}

    if user_name in server.user_name_to_id_map:
        return server.user_name_to_id_map[user_name]

    cursor = None
    while True:
        pagination_params = {"limit": 200}
        if cursor:
            pagination_params["cursor"] = cursor

        response = slack_client.users_list(**pagination_params)

        for user in response["members"]:
            if user.get("name"):
                server.user_name_to_id_map[user.get("name")] = user["id"]
            if user.get("real_name"):
                server.user_name_to_id_map[user.get("real_name")] = user["id"]

            if user.get("name") == user_name or user.get("real_name") == user_name:
                return user["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return None


def create_server(user_id, api_key=None):
    """Create a new server instance for Slack user-token posting.

    This server uses user-level OAuth tokens (xoxp-) so that all messages
    are posted as the authenticated user — their real display name, avatar,
    and no bot badge. A 'Sent from 20x' footer is appended to outgoing
    messages for transparency.
    """
    server = Server("slack-user-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List Slack channels"""
        logger.info(
            f"Listing resources for user: {server.user_id} with cursor: {cursor}"
        )

        slack_client = await create_slack_client(server.user_id, api_key=server.api_key)

        try:
            resources = []

            response = slack_client.conversations_list(
                types="public_channel,private_channel", limit=100, cursor=cursor or None
            )

            channels = response.get("channels", [])

            for channel in channels:
                channel_id = channel.get("id")
                channel_name = channel.get("name")
                is_private = channel.get("is_private", False)

                resource = Resource(
                    uri=f"slack://channel/{channel_id}",
                    mimeType="text/plain",
                    name=f"#{channel_name}",
                    description=f"{'Private' if is_private else 'Public'} Slack channel: #{channel_name}",
                )
                resources.append(resource)

            return resources

        except SlackApiError as e:
            logger.error(f"Error listing Slack resources: {e}")
            return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read resources from Slack"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        slack_client = await create_slack_client(server.user_id, api_key=server.api_key)

        uri_str = str(uri)
        if not uri_str.startswith("slack://"):
            raise ValueError(f"Invalid Slack URI: {uri_str}")

        parts = uri_str.replace("slack://", "").split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid Slack URI format: {uri_str}")

        resource_type, resource_id = parts

        try:
            if resource_type == "channel":
                response = slack_client.conversations_history(
                    channel=resource_id, limit=50
                )

                messages = response.get("messages", [])
                messages.reverse()

                enriched_messages = []
                for message in messages:
                    enriched_message = await enrich_message_with_user_info(
                        slack_client, message
                    )
                    enriched_messages.append(enriched_message)

                return [
                    ReadResourceContents(
                        content=json.dumps(enriched_messages, indent=2),
                        mime_type="application/json",
                    )
                ]

            else:
                raise ValueError(f"Unknown resource type: {resource_type}")

        except SlackApiError as e:
            logger.error(f"Error reading Slack resource: {e}")
            return [
                ReadResourceContents(content=f"Error: {str(e)}", mime_type="text/plain")
            ]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools"""
        logger.info(f"Listing tools for user: {server.user_id}")
        return [
            Tool(
                name="read_messages",
                description="Read messages from a Slack channel",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Slack channel ID or name (with # for names)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to return (default: 20)",
                        },
                    },
                    "required": ["channel"],
                },
                requiredScopes=["channels:history", "groups:history", "im:read"],
            ),
            Tool(
                name="send_message",
                description=(
                    "Send a message to a Slack channel or user as the authenticated user. "
                    "The message appears from the user's real name and avatar (no bot badge). "
                    "A 'Sent from 20x' footer is automatically appended for transparency."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Slack channel ID or name (with # for channel names, @ for usernames)",
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text to send",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Optional thread timestamp to reply to a thread",
                        },
                    },
                    "required": ["channel", "text"],
                },
                requiredScopes=["chat:write"],
            ),
            Tool(
                name="create_canvas",
                description=(
                    "Create a Slack canvas message with rich content as the authenticated user. "
                    "A 'Sent from 20x' footer is automatically appended for transparency."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Slack channel ID or name (with # for names)",
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the canvas",
                        },
                        "blocks": {
                            "type": "array",
                            "description": "Array of Slack block kit elements as JSON objects",
                            "items": {"type": "object"},
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Optional thread timestamp to attach canvas to a thread",
                        },
                    },
                    "required": ["channel", "title", "blocks"],
                },
                requiredScopes=["chat:write"],
            ),
            Tool(
                name="react_to_message",
                description="Add a reaction to a message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Channel ID or name where the message is located",
                        },
                        "timestamp": {
                            "type": "string",
                            "description": "Timestamp of the message to react to",
                        },
                        "reaction": {
                            "type": "string",
                            "description": "Emoji name to use as reaction (without colons)",
                        },
                    },
                    "required": ["channel", "timestamp", "reaction"],
                },
                requiredScopes=["reactions:write"],
            ),
            Tool(
                name="delete_message",
                description="Delete a Slack message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Channel ID or name where the message is located",
                        },
                        "timestamp": {
                            "type": "string",
                            "description": "Timestamp of the message to delete",
                        },
                    },
                    "required": ["channel", "timestamp"],
                },
                requiredScopes=["chat:write"],
            ),
            Tool(
                name="get_message_thread",
                description="Retrieve a message and its replies",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Channel ID or name where the thread is located",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Timestamp of the parent message of the thread",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of replies to return",
                        },
                    },
                    "required": ["channel", "thread_ts"],
                },
                requiredScopes=["channels:history", "groups:history", "im:read"],
            ),
            Tool(
                name="get_user_presence",
                description="Check a user's online status",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user": {
                            "type": "string",
                            "description": "User ID or email to check presence for",
                        },
                    },
                    "required": ["user"],
                },
                requiredScopes=["users:read"],
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

        slack_client = await create_slack_client(server.user_id, api_key=server.api_key)

        def raw_response_processor(response):
            """Process Slack API responses into JSON"""
            if hasattr(response, "data"):
                response = response.data

            if isinstance(response, list):
                return [
                    TextContent(type="text", text=json.dumps(item, indent=2))
                    for item in response
                ]

            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        tool_config = {
            "read_messages": {
                "handler": lambda args: slack_client.conversations_history(
                    channel=args["resolved_channel"], limit=args.get("limit", 20)
                ),
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    ),
                    "limit": args.get("limit", 20),
                },
                "postprocess": lambda response: [
                    TextContent(type="text", text=json.dumps(message, indent=2))
                    for message in enrich_messages_sync(
                        slack_client, response.get("messages", [])
                    )
                ],
            },
            "send_message": {
                "handler": lambda args: slack_client.chat_postMessage(
                    channel=args["resolved_channel"],
                    text=args["text"],
                    thread_ts=args.get("thread_ts"),
                ),
                "preprocess": lambda args: {
                    "resolved_channel": get_channel_or_user_id(
                        slack_client, server, args["channel"]
                    ),
                    "text": append_footer(args["text"]),
                    "thread_ts": args.get("thread_ts"),
                },
                "postprocess": lambda response: [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            [
                                {
                                    "status": "success",
                                    "channel": response["channel"],
                                    "ts": response["ts"],
                                    "message": response.get("message", {}),
                                }
                            ],
                            indent=2,
                        ),
                    )
                ],
            },
            "create_canvas": {
                "handler": lambda args: slack_client.chat_postMessage(
                    channel=args["resolved_channel"],
                    blocks=process_blocks(args["blocks"], args["title"]),
                    text=append_footer(args["title"]),
                    thread_ts=args.get("thread_ts"),
                ),
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    ),
                    "title": args["title"],
                    "blocks": args["blocks"],
                    "thread_ts": args.get("thread_ts"),
                },
                "postprocess": lambda response: [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            [
                                {
                                    "status": "success",
                                    "channel": response["channel"],
                                    "ts": response["ts"],
                                    "message": response.get("message", {}),
                                }
                            ],
                            indent=2,
                        ),
                    )
                ],
            },
            "get_message_thread": {
                "handler": lambda args: {
                    "parent": slack_client.conversations_history(
                        channel=args["resolved_channel"],
                        latest=args["thread_ts"],
                        limit=1,
                        inclusive=True,
                    ),
                    "replies": slack_client.conversations_replies(
                        channel=args["resolved_channel"],
                        ts=args["thread_ts"],
                        limit=args.get("limit", 20),
                    ),
                },
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    ),
                    "thread_ts": args["thread_ts"],
                    "limit": args.get("limit", 20),
                },
                "postprocess": lambda response: [
                    TextContent(type="text", text=json.dumps(message, indent=2))
                    for message in enrich_messages_sync(
                        slack_client, response["replies"].get("messages", [])
                    )
                ],
            },
            "list_pinned_items": {
                "handler": lambda args: slack_client.pins_list(
                    channel=args["resolved_channel"]
                ),
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    )
                },
                "postprocess": lambda response: [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            enrich_message_with_user_info_sync(slack_client, item),
                            indent=2,
                        ),
                    )
                    for item in response.get("items", [])
                ],
            },
            "react_to_message": {
                "handler": lambda args: slack_client.reactions_add(
                    channel=args["resolved_channel"],
                    timestamp=args["timestamp"],
                    name=args["clean_reaction"],
                ),
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    ),
                    "timestamp": args["timestamp"],
                    "clean_reaction": (
                        args["reaction"].strip(":")
                        if args["reaction"].startswith(":")
                        and args["reaction"].endswith(":")
                        else args["reaction"]
                    ),
                },
            },
            "delete_message": {
                "handler": lambda args: slack_client.chat_delete(
                    channel=args["resolved_channel"], ts=args["timestamp"]
                ),
                "preprocess": lambda args: {
                    "resolved_channel": (
                        get_channel_id_sync(slack_client, server, args["channel"])
                        if args["channel"].startswith("#")
                        else args["channel"]
                    ),
                    "timestamp": args["timestamp"],
                },
            },
            "get_user_presence": {
                "handler": lambda args: slack_client.users_getPresence(
                    user=args["resolved_user"]
                ),
                "preprocess": lambda args: {
                    "resolved_user": (
                        get_user_id_sync(slack_client, server, args["user"])
                        if "@" in args["user"] or not args["user"].startswith("U")
                        else args["user"]
                    )
                },
            },
        }

        try:
            if name in tool_config:
                config = tool_config[name]

                args = config["preprocess"](arguments)
                response = config["handler"](args)

                if "postprocess" in config:
                    return config["postprocess"](response)
                return raw_response_processor(response)
            else:
                error_response = {"error": f"Unknown tool: {name}"}
                return [
                    TextContent(type="text", text=json.dumps(error_response, indent=2))
                ]

        except SlackApiError as e:
            logger.error(f"Slack API error: {e}")
            error_response = {"error": str(e)}
            return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="slack-user-server",
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
        print("Note: To run the server normally, use the pfMCP server framework.")


# Helper functions for the refactored approach
def get_channel_id_sync(slack_client, server, channel):
    """Synchronous wrapper to get channel ID from channel name"""
    if not channel.startswith("#"):
        return channel

    channel_name = channel[1:]

    if not hasattr(server, "channel_name_to_id_map"):
        server.channel_name_to_id_map = {}

    if channel_name in server.channel_name_to_id_map:
        return server.channel_name_to_id_map[channel_name]

    cursor = None
    while True:
        pagination_params = {
            "types": "public_channel,private_channel",
            "limit": 200,
        }
        if cursor:
            pagination_params["cursor"] = cursor

        response = slack_client.conversations_list(**pagination_params)

        for ch in response["channels"]:
            server.channel_name_to_id_map[ch["name"]] = ch["id"]
            if ch["name"] == channel_name:
                return ch["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    raise ValueError(f"Channel {channel} not found")


def get_user_id_sync(slack_client, server, user):
    """Synchronous wrapper to get user ID from username or email"""
    if "@" in user:
        response = slack_client.users_lookupByEmail(email=user)
        if response["ok"]:
            return response["user"]["id"]
        else:
            raise ValueError(f"User with email {user} not found")

    if user.startswith("U"):
        return user

    if not hasattr(server, "user_name_to_id_map"):
        server.user_name_to_id_map = {}

    if user in server.user_name_to_id_map:
        return server.user_name_to_id_map[user]

    cursor = None
    while True:
        pagination_params = {"limit": 200}
        if cursor:
            pagination_params["cursor"] = cursor

        response = slack_client.users_list(**pagination_params)

        for u in response["members"]:
            if u.get("name"):
                server.user_name_to_id_map[u.get("name")] = u["id"]
            if u.get("real_name"):
                server.user_name_to_id_map[u.get("real_name")] = u["id"]

            if u.get("name") == user or u.get("real_name") == user:
                return u["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    raise ValueError(f"User {user} not found")


def get_channel_or_user_id(slack_client, server, channel_or_user):
    """Resolve channel or user references to IDs"""
    if channel_or_user.startswith("#"):
        return get_channel_id_sync(slack_client, server, channel_or_user)
    elif channel_or_user.startswith("@"):
        user_name = channel_or_user[1:]
        user_id = get_user_id_sync(slack_client, server, user_name)

        dm_response = slack_client.conversations_open(users=user_id)
        return dm_response["channel"]["id"]
    else:
        return channel_or_user


def process_blocks(blocks, title):
    """Process blocks for canvas creation"""
    if blocks is None:
        blocks = []

    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except json.JSONDecodeError:
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": blocks}}]

    if not isinstance(blocks, list):
        blocks = [blocks]

    has_header = False
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "header":
            has_header = True
            break

    if not has_header and blocks:
        blocks.insert(
            0, {"type": "header", "text": {"type": "plain_text", "text": title}}
        )

    # Append a footer section for transparency
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Sent from <https://peakflo.co/20x-agent-orchestrator|20x>_",
                },
            ],
        }
    )

    return blocks


def format_emoji(emoji):
    """Format emoji for status"""
    if not emoji.startswith(":"):
        emoji = f":{emoji}"
    if not emoji.endswith(":"):
        emoji = f"{emoji}:"
    return emoji


def enrich_message_with_user_info_sync(slack_client, message):
    """Synchronous version of enrich_message_with_user_info"""
    user_id = message.get("user", "Unknown")

    if user_id != "Unknown":
        try:
            user_info = slack_client.users_info(user=user_id)
            if user_info["ok"]:
                user_data = user_info["user"]
                message["user_name"] = user_data.get("real_name") or user_data.get(
                    "name", "Unknown"
                )
                message["user_profile"] = user_data.get("profile", {})
        except SlackApiError:
            message["user_name"] = "Unknown"

    return message


def enrich_pinned_items(slack_client, items):
    """Enrich pinned items with user info"""
    for item in items:
        if item.get("type") == "message":
            message = item.get("message", {})
            item["message"] = enrich_message_with_user_info_sync(slack_client, message)
    return items


def enrich_messages_sync(slack_client, messages):
    """Enrich and reverse a list of messages"""
    # Reverse to get chronological order
    messages_copy = messages.copy()
    messages_copy.reverse()

    # Enrich messages with user information
    enriched_messages = []
    for message in messages_copy:
        enriched_message = enrich_message_with_user_info_sync(slack_client, message)
        enriched_messages.append(enriched_message)

    return enriched_messages
