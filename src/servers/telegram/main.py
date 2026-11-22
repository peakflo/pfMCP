"""Telegram (user account) MCP tools built on Telethon.

The tool set and the Telethon usage are adapted from chigwell/telegram-mcp
(https://github.com/chigwell/telegram-mcp), licensed under the Apache License
2.0. This module is a rewrite for the pfMCP server framework: every tool call
opens a Telethon client from a stored ``StringSession`` and closes it again.
The server never logs in interactively.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging

from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool
from telethon import TelegramClient, errors, functions, types, utils
from telethon.sessions import StringSession

from src.auth.credential_errors import REVOKED, CredentialError
from src.utils.mcp_compat import NotificationOptions, Server
from src.utils.telegram.util import authenticate_and_save_credentials, get_credentials

SERVICE_NAME = Path(__file__).parent.name

# Telethon sleeps through short flood waits on its own; keep that short so a
# tool call fails fast instead of holding the request open.
FLOOD_SLEEP_THRESHOLD = 5
TOOL_TIMEOUT_SECONDS = float(os.environ.get("TELEGRAM_TOOL_TIMEOUT_SECONDS", "60"))
# Dialogs loaded to warm Telethon's entity cache when a numeric chat ID is
# not known yet (a StringSession starts with an empty cache).
DIALOG_WARMUP_LIMIT = 500

MAX_DIALOGS = 200
MAX_MESSAGES = 100
MAX_PARTICIPANTS = 500
MAX_MESSAGE_IDS = 100

_REVOKED_ERRORS = (
    errors.AuthKeyUnregisteredError,
    errors.AuthKeyDuplicatedError,
    errors.SessionRevokedError,
    errors.SessionExpiredError,
    errors.UserDeactivatedError,
    errors.UserDeactivatedBanError,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def create_telegram_client(credentials: Dict[str, Any]) -> TelegramClient:
    """Build a Telethon client from ``api_id``, ``api_hash`` and ``session_string``."""
    return TelegramClient(
        StringSession(credentials["session_string"]),
        credentials["api_id"],
        credentials["api_hash"],
        receive_updates=False,
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD,
        connection_retries=2,
        request_retries=2,
        timeout=10,
    )


async def connect_client(user_id: str, api_key: Optional[str] = None):
    """Return a connected, authorized Telethon client for the connection."""
    credentials = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    client = create_telegram_client(credentials)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
    except _REVOKED_ERRORS:
        authorized = False
    if not authorized:
        await client.disconnect()
        raise CredentialError(SERVICE_NAME, REVOKED)
    return client


# --------------------------------------------------------------------------- #
# Argument helpers
# --------------------------------------------------------------------------- #
_NUMERIC_ID = re.compile(r"^-?\d+$")


def parse_peer(value: Any, field: str = "chat_id") -> Any:
    """Turn a tool argument into something ``get_entity`` accepts.

    Numeric strings become ints; usernames, ``@username``, phone numbers,
    t.me links and ``me`` pass through unchanged.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is required")
    if _NUMERIC_ID.match(text):
        return int(text)
    if text.lower() in ("me", "self"):
        return "me"
    return text


def _limit(arguments: Dict[str, Any], default: int, maximum: int) -> int:
    value = arguments.get("limit", default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer")
    return max(1, min(value, maximum))


def _message_ids(arguments: Dict[str, Any]) -> List[int]:
    raw = arguments.get("message_ids")
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError("message_ids must be a non-empty list of message IDs")
    if len(raw) > MAX_MESSAGE_IDS:
        raise ValueError(f"message_ids accepts at most {MAX_MESSAGE_IDS} IDs")
    try:
        return [int(item) for item in raw]
    except (TypeError, ValueError):
        raise ValueError("message_ids must contain integers")


def _required_int(arguments: Dict[str, Any], field: str) -> int:
    value = arguments.get(field)
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} is required")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")


def _required_text(arguments: Dict[str, Any], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _parse_mode(arguments: Dict[str, Any]) -> Optional[str]:
    mode = arguments.get("parse_mode", "md")
    if mode in (None, "", "none", "text"):
        return None
    if mode not in ("md", "markdown", "html"):
        raise ValueError("parse_mode must be one of: md, html, none")
    return mode


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else None


def entity_type(entity: Any) -> str:
    if isinstance(entity, types.User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        return "group"
    if isinstance(entity, (types.Channel, types.ChannelForbidden)):
        return "supergroup" if getattr(entity, "megagroup", False) else "channel"
    return type(entity).__name__


def format_entity(entity: Any) -> Dict[str, Any]:
    """Describe a user, group or channel."""
    result: Dict[str, Any] = {
        "id": utils.get_peer_id(entity),
        "type": entity_type(entity),
        "name": utils.get_display_name(entity),
    }
    username = getattr(entity, "username", None)
    if username:
        result["username"] = username
    if isinstance(entity, types.User):
        for field in ("first_name", "last_name", "phone"):
            value = getattr(entity, field, None)
            if value:
                result[field] = value
        for flag in ("bot", "contact", "mutual_contact", "verified", "premium"):
            if getattr(entity, flag, False):
                result[flag] = True
    else:
        count = getattr(entity, "participants_count", None)
        if count is not None:
            result["participants_count"] = count
    return result


def format_message(message: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": message.id,
        "date": _iso(message.date),
        "text": message.message or "",
        "out": bool(getattr(message, "out", False)),
    }
    if getattr(message, "peer_id", None) is not None:
        result["chat_id"] = utils.get_peer_id(message.peer_id)
    if getattr(message, "from_id", None) is not None:
        result["sender_id"] = utils.get_peer_id(message.from_id)
    elif result.get("chat_id") is not None and not result["out"]:
        # Private chats and channel posts carry no from_id.
        result["sender_id"] = result["chat_id"]
    reply_to = getattr(message, "reply_to", None)
    reply_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
    if reply_id:
        result["reply_to_message_id"] = reply_id
    if getattr(message, "fwd_from", None) is not None:
        result["forwarded"] = True
    if getattr(message, "edit_date", None):
        result["edit_date"] = _iso(message.edit_date)
    if getattr(message, "media", None) is not None:
        result["media_type"] = type(message.media).__name__
    return result


def format_dialog(dialog: Any) -> Dict[str, Any]:
    result = format_entity(dialog.entity)
    result["unread_count"] = dialog.unread_count
    if getattr(dialog, "pinned", False):
        result["pinned"] = True
    if getattr(dialog, "archived", False):
        result["archived"] = True
    if getattr(dialog, "message", None) is not None:
        result["last_message"] = format_message(dialog.message)
    return result


# --------------------------------------------------------------------------- #
# Entity resolution
# --------------------------------------------------------------------------- #
async def resolve_entity(client: TelegramClient, peer: Any) -> Any:
    """Resolve an ID, username, phone or link to an entity.

    A StringSession has no entity cache, so the first lookup of a numeric ID
    can fail; loading dialogs fills the cache and the lookup is retried.
    """
    try:
        return await client.get_entity(peer)
    except ValueError:
        if not isinstance(peer, int):
            raise
    await client.get_dialogs(limit=DIALOG_WARMUP_LIMIT)
    try:
        return await client.get_entity(peer)
    except ValueError:
        raise ValueError(
            f"Telegram chat or user {peer} was not found. Use list_chats to get "
            "a valid ID, or pass a @username."
        )


async def _full_about(client: TelegramClient, entity: Any) -> Dict[str, Any]:
    """Extra details (bio/description, member count) from the full entity."""
    try:
        if isinstance(entity, types.User):
            full = await client(functions.users.GetFullUserRequest(entity))
            return {"about": full.full_user.about}
        if isinstance(entity, types.Channel):
            full = await client(functions.channels.GetFullChannelRequest(entity))
            return {
                "about": full.full_chat.about,
                "participants_count": full.full_chat.participants_count,
            }
        if isinstance(entity, types.Chat):
            full = await client(functions.messages.GetFullChatRequest(entity.id))
            participants = getattr(full.full_chat.participants, "participants", None)
            return {
                "about": full.full_chat.about,
                "participants_count": (
                    len(participants) if participants is not None else None
                ),
            }
    except errors.RPCError as error:
        logger.info(f"Full entity lookup failed: {type(error).__name__}")
    return {}


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
async def tool_get_me(client: TelegramClient, arguments: Dict[str, Any]):
    return format_entity(await client.get_me())


async def tool_list_chats(client: TelegramClient, arguments: Dict[str, Any]):
    limit = _limit(arguments, 20, MAX_DIALOGS)
    chat_type = arguments.get("chat_type")
    unread_only = bool(arguments.get("unread_only", False))
    archived = bool(arguments.get("archived", False))
    # Filters are applied after fetching, so fetch more when filtering.
    fetch = MAX_DIALOGS if (chat_type or unread_only) else limit
    dialogs = await client.get_dialogs(limit=fetch, archived=archived)
    chats = []
    for dialog in dialogs:
        item = format_dialog(dialog)
        if chat_type and item["type"] != chat_type:
            continue
        if unread_only and not item["unread_count"]:
            continue
        chats.append(item)
        if len(chats) >= limit:
            break
    return {"chats": chats, "count": len(chats)}


async def tool_get_chat(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    result = format_entity(entity)
    for key, value in (await _full_about(client, entity)).items():
        if value is not None:
            result[key] = value
    return result


async def tool_get_messages(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    limit = _limit(arguments, 20, MAX_MESSAGES)
    kwargs: Dict[str, Any] = {}
    for field in ("offset_id", "min_id"):
        if arguments.get(field) is not None:
            kwargs[field] = _required_int(arguments, field)
    messages = await client.get_messages(entity, limit=limit, **kwargs)
    items = [format_message(message) for message in messages]
    result: Dict[str, Any] = {"chat_id": utils.get_peer_id(entity), "messages": items}
    if len(items) == limit:
        result["next_offset_id"] = min(item["id"] for item in items)
    return result


async def tool_search_messages(client: TelegramClient, arguments: Dict[str, Any]):
    query = _required_text(arguments, "query")
    limit = _limit(arguments, 20, MAX_MESSAGES)
    entity = None
    if arguments.get("chat_id") not in (None, ""):
        entity = await resolve_entity(client, parse_peer(arguments["chat_id"]))
    kwargs: Dict[str, Any] = {"search": query, "limit": limit}
    if arguments.get("from_user") not in (None, ""):
        if entity is None:
            raise ValueError("from_user requires chat_id")
        kwargs["from_user"] = await resolve_entity(
            client, parse_peer(arguments["from_user"], "from_user")
        )
    messages = await client.get_messages(entity, **kwargs)
    return {"query": query, "messages": [format_message(m) for m in messages]}


async def tool_send_message(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    text = _required_text(arguments, "text")
    kwargs: Dict[str, Any] = {"parse_mode": _parse_mode(arguments)}
    if arguments.get("reply_to_message_id") is not None:
        kwargs["reply_to"] = _required_int(arguments, "reply_to_message_id")
    if arguments.get("silent") is not None:
        kwargs["silent"] = bool(arguments["silent"])
    message = await client.send_message(entity, text, **kwargs)
    return {"sent": True, "message": format_message(message)}


async def tool_edit_message(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    message_id = _required_int(arguments, "message_id")
    text = _required_text(arguments, "text")
    message = await client.edit_message(
        entity, message_id, text, parse_mode=_parse_mode(arguments)
    )
    return {"edited": True, "message": format_message(message)}


async def tool_delete_messages(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    ids = _message_ids(arguments)
    revoke = bool(arguments.get("revoke", True))
    affected = await client.delete_messages(entity, ids, revoke=revoke)
    deleted = sum(getattr(item, "pts_count", 0) for item in affected or [])
    return {"deleted_count": deleted, "message_ids": ids, "revoke": revoke}


async def tool_forward_messages(client: TelegramClient, arguments: Dict[str, Any]):
    source = await resolve_entity(
        client, parse_peer(arguments.get("from_chat_id"), "from_chat_id")
    )
    target = await resolve_entity(
        client, parse_peer(arguments.get("to_chat_id"), "to_chat_id")
    )
    ids = _message_ids(arguments)
    forwarded = await client.forward_messages(target, ids, source)
    if not isinstance(forwarded, list):
        forwarded = [forwarded]
    return {
        "forwarded_count": len([m for m in forwarded if m is not None]),
        "messages": [format_message(m) for m in forwarded if m is not None],
    }


async def tool_mark_as_read(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    kwargs: Dict[str, Any] = {}
    if arguments.get("max_message_id") is not None:
        kwargs["max_id"] = _required_int(arguments, "max_message_id")
    ok = await client.send_read_acknowledge(entity, **kwargs)
    return {"marked_as_read": bool(ok), "chat_id": utils.get_peer_id(entity)}


async def tool_list_contacts(client: TelegramClient, arguments: Dict[str, Any]):
    result = await client(functions.contacts.GetContactsRequest(hash=0))
    users = getattr(result, "users", None) or []
    limit = _limit(arguments, 100, 1000)
    contacts = [format_entity(user) for user in users][:limit]
    return {"contacts": contacts, "count": len(contacts), "total": len(users)}


async def tool_get_user(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("user"), "user"))
    result = format_entity(entity)
    for key, value in (await _full_about(client, entity)).items():
        if value is not None:
            result[key] = value
    return result


async def tool_resolve_username(client: TelegramClient, arguments: Dict[str, Any]):
    username = _required_text(arguments, "username").strip()
    username = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)", "", username)
    username = username.lstrip("@").split("/")[0]
    if not re.match(r"^[A-Za-z0-9_]{4,32}$", username):
        raise ValueError("username must be a Telegram username such as @example")
    return format_entity(await client.get_entity(username))


async def tool_get_participants(client: TelegramClient, arguments: Dict[str, Any]):
    entity = await resolve_entity(client, parse_peer(arguments.get("chat_id")))
    limit = _limit(arguments, 100, MAX_PARTICIPANTS)
    filters = {
        "all": None,
        "admins": types.ChannelParticipantsAdmins(),
        "bots": types.ChannelParticipantsBots(),
    }
    kind = arguments.get("filter") or "all"
    if kind not in filters:
        raise ValueError("filter must be one of: all, admins, bots")
    participants = await client.get_participants(
        entity,
        limit=limit,
        search=arguments.get("search") or "",
        filter=filters[kind],
    )
    return {
        "chat_id": utils.get_peer_id(entity),
        "participants": [format_entity(user) for user in participants],
        "total": getattr(participants, "total", None),
    }


TOOL_HANDLERS = {
    "get_me": tool_get_me,
    "list_chats": tool_list_chats,
    "get_chat": tool_get_chat,
    "get_messages": tool_get_messages,
    "search_messages": tool_search_messages,
    "send_message": tool_send_message,
    "edit_message": tool_edit_message,
    "delete_messages": tool_delete_messages,
    "forward_messages": tool_forward_messages,
    "mark_as_read": tool_mark_as_read,
    "list_contacts": tool_list_contacts,
    "get_user": tool_get_user,
    "resolve_username": tool_resolve_username,
    "get_participants": tool_get_participants,
}


def _chat_id_property(description: str = "Chat to use") -> Dict[str, Any]:
    return {
        "type": "string",
        "description": (
            f"{description}: a numeric ID from list_chats (for example "
            "-1001234567890), a @username, a t.me link, a phone number, or 'me' "
            "for Saved Messages"
        ),
    }


_LIMIT = {"type": "integer", "minimum": 1}
_PARSE_MODE = {
    "type": "string",
    "enum": ["md", "html", "none"],
    "default": "md",
    "description": "Text formatting: Markdown (md), HTML, or plain text (none)",
}
_MESSAGE_IDS = {
    "type": "array",
    "items": {"type": "integer"},
    "minItems": 1,
    "maxItems": MAX_MESSAGE_IDS,
    "description": "Message IDs",
}


def tool_definitions() -> List[Tool]:
    return [
        Tool(
            name="get_me",
            description="Get the connected Telegram account's profile",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_chats",
            description=(
                "List the account's chats (dialogs), most recent first, with "
                "unread counts and the last message"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {**_LIMIT, "maximum": MAX_DIALOGS, "default": 20},
                    "chat_type": {
                        "type": "string",
                        "enum": ["user", "bot", "group", "supergroup", "channel"],
                        "description": "Only return chats of this type",
                    },
                    "unread_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only return chats with unread messages",
                    },
                    "archived": {
                        "type": "boolean",
                        "default": False,
                        "description": "List archived chats instead of the main list",
                    },
                },
            },
        ),
        Tool(
            name="get_chat",
            description="Get details of a chat, group, channel or user",
            inputSchema={
                "type": "object",
                "properties": {"chat_id": _chat_id_property()},
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_messages",
            description=(
                "Get messages from a chat, newest first. Pass next_offset_id back "
                "as offset_id to get older messages"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "limit": {**_LIMIT, "maximum": MAX_MESSAGES, "default": 20},
                    "offset_id": {
                        "type": "integer",
                        "description": "Only return messages older than this ID",
                    },
                    "min_id": {
                        "type": "integer",
                        "description": "Only return messages newer than this ID",
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="search_messages",
            description=(
                "Search messages by text in one chat, or across all chats when "
                "chat_id is omitted"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                    "chat_id": _chat_id_property("Chat to search (optional)"),
                    "from_user": {
                        "type": "string",
                        "description": (
                            "Only messages from this user (ID or @username); "
                            "requires chat_id"
                        ),
                    },
                    "limit": {**_LIMIT, "maximum": MAX_MESSAGES, "default": 20},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="send_message",
            description="Send a text message to a chat as the connected user",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Chat to send to"),
                    "text": {"type": "string", "description": "Message text"},
                    "reply_to_message_id": {
                        "type": "integer",
                        "description": "Reply to this message ID",
                    },
                    "parse_mode": _PARSE_MODE,
                    "silent": {
                        "type": "boolean",
                        "description": "Send without a notification sound",
                    },
                },
                "required": ["chat_id", "text"],
            },
        ),
        Tool(
            name="edit_message",
            description="Edit the text of a message the connected user sent",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_id": {"type": "integer", "description": "Message ID"},
                    "text": {"type": "string", "description": "New message text"},
                    "parse_mode": _PARSE_MODE,
                },
                "required": ["chat_id", "message_id", "text"],
            },
        ),
        Tool(
            name="delete_messages",
            description="Delete messages from a chat",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_ids": _MESSAGE_IDS,
                    "revoke": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Delete for everyone (true) or only for the "
                            "connected user (false)"
                        ),
                    },
                },
                "required": ["chat_id", "message_ids"],
            },
        ),
        Tool(
            name="forward_messages",
            description="Forward messages from one chat to another",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_chat_id": _chat_id_property("Chat the messages are in"),
                    "to_chat_id": _chat_id_property("Chat to forward to"),
                    "message_ids": _MESSAGE_IDS,
                },
                "required": ["from_chat_id", "to_chat_id", "message_ids"],
            },
        ),
        Tool(
            name="mark_as_read",
            description="Mark messages in a chat as read",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "max_message_id": {
                        "type": "integer",
                        "description": (
                            "Mark messages up to this ID as read; defaults to all"
                        ),
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="list_contacts",
            description="List the connected user's Telegram contacts",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {**_LIMIT, "maximum": 1000, "default": 100},
                },
            },
        ),
        Tool(
            name="get_user",
            description="Get a Telegram user's profile by ID, @username or phone",
            inputSchema={
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "User ID, @username, phone number or 'me'",
                    }
                },
                "required": ["user"],
            },
        ),
        Tool(
            name="resolve_username",
            description="Find the user, group or channel that owns a @username",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username, with or without @, or a t.me link",
                    }
                },
                "required": ["username"],
            },
        ),
        Tool(
            name="get_participants",
            description="List members of a group or channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Group or channel"),
                    "limit": {**_LIMIT, "maximum": MAX_PARTICIPANTS, "default": 100},
                    "search": {
                        "type": "string",
                        "description": "Only members whose name matches",
                    },
                    "filter": {
                        "type": "string",
                        "enum": ["all", "admins", "bots"],
                        "default": "all",
                    },
                },
                "required": ["chat_id"],
            },
        ),
    ]


async def execute_tool(
    user_id: str, name: str, arguments: Dict[str, Any], api_key: Optional[str] = None
) -> Any:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    client = await connect_client(user_id, api_key=api_key)
    try:
        return await asyncio.wait_for(
            handler(client, arguments), timeout=TOOL_TIMEOUT_SECONDS
        )
    except _REVOKED_ERRORS:
        raise CredentialError(SERVICE_NAME, REVOKED)
    except errors.FloodWaitError as error:
        raise ValueError(
            f"Telegram rate limit reached. Try again in {error.seconds} seconds."
        )
    except asyncio.TimeoutError:
        raise ValueError(
            f"Telegram did not answer within {int(TOOL_TIMEOUT_SECONDS)} seconds."
        )
    except errors.RPCError as error:
        raise ValueError(f"Telegram error: {error}")
    finally:
        await client.disconnect()


def create_server(user_id: str, api_key: Optional[str] = None) -> Server:
    server = Server("telegram-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return tool_definitions()

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        logger.info(f"User {server.user_id} calling tool: {name}")
        result = await execute_tool(
            server.user_id, name, arguments or {}, api_key=server.api_key
        )
        return [
            TextContent(
                type="text", text=json.dumps(result, default=str, ensure_ascii=False)
            )
        ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="telegram-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        authenticate_and_save_credentials("local", SERVICE_NAME, [])
    else:
        print("Usage:")
        print("  python main.py auth - Save Telegram credentials for local use")
        print("Note: To run the server normally, use the pfMCP server framework.")
