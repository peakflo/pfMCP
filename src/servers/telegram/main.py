"""Telegram Bot API MCP server.

Every tool is one Bot API method called with plain ``httpx`` at
``https://api.telegram.org/bot<token>/<method>``. The bot token comes from the
connection (Nango ``credentials.apiKey``) on every call and is masked out of
logs, errors and tool results.

``getUpdates`` is deliberately not exposed: it would consume the updates that
a webhook (planned in workflow-builder) needs.
"""

import asyncio
import base64
import binascii
import hashlib
import json
import mimetypes
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging

import httpx
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from src.auth.credential_errors import REVOKED, CredentialError
from src.utils.mcp_compat import NotificationOptions, Server
from src.utils.telegram.util import (
    authenticate_and_save_credentials,
    get_credentials,
    install_log_masking,
    mask_token,
)

SERVICE_NAME = Path(__file__).parent.name
API_BASE = "https://api.telegram.org"

REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
UPLOAD_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Bot API limits.
MAX_TEXT_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PHOTO_UPLOAD_BYTES = 10 * 1024 * 1024

# A 429 is retried once when Telegram asks to wait at most this long.
MAX_RETRY_AFTER_SECONDS = 5
# Client-side pacing: about 1 message/second per chat and 20/minute per group.
PER_CHAT_INTERVAL_SECONDS = 1.0
GROUP_WINDOW_SECONDS = 60.0
GROUP_MAX_PER_WINDOW = 20
# Longest a call waits for its pacing slot before it fails instead.
MAX_PACING_WAIT_SECONDS = 5.0

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)
install_log_masking()


async def _sleep(seconds: float) -> None:
    """Indirection so tests do not wait."""
    await asyncio.sleep(seconds)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class TelegramError(ValueError):
    """A Bot API failure. ``str(error)`` starts with a stable ``[code]``."""

    def __init__(self, code: str, message: str, **details: Any):
        self.code = code
        self.details = details
        super().__init__(f"[{code}] {message}")


FORBIDDEN = "telegram_forbidden"
RATE_LIMITED = "telegram_rate_limited"
BAD_REQUEST = "telegram_bad_request"
API_ERROR = "telegram_error"
NETWORK_ERROR = "telegram_unreachable"


def error_from_response(
    status: int, body: Dict[str, Any], token: Optional[str]
) -> Exception:
    """Map a failed Bot API answer to a credential or Telegram error."""
    code = body.get("error_code", status)
    description = mask_token(body.get("description") or "no description", token)
    parameters = body.get("parameters") or {}
    if code == 401 or (code == 404 and description == "Not Found"):
        # 401 Unauthorized: token revoked or regenerated in @BotFather.
        # 404 on the method itself: the token does not name a bot.
        return CredentialError(SERVICE_NAME, REVOKED)
    if code == 403:
        return TelegramError(
            FORBIDDEN,
            f"Telegram refused the request: {description}. The user may have "
            "blocked the bot or never pressed /start, or the bot was removed from "
            "the chat or lacks the admin right this action needs.",
        )
    if code == 429:
        retry_after = parameters.get("retry_after")
        return TelegramError(
            RATE_LIMITED,
            f"Telegram rate limit reached. Retry after {retry_after} seconds.",
            retry_after=retry_after,
        )
    if code == 400:
        message = f"Telegram rejected the request: {description}"
        migrate_to = parameters.get("migrate_to_chat_id")
        if migrate_to:
            message += f". The group is now a supergroup with chat_id {migrate_to}"
        return TelegramError(BAD_REQUEST, message, migrate_to_chat_id=migrate_to)
    return TelegramError(API_ERROR, f"Telegram error {code}: {description}")


# --------------------------------------------------------------------------- #
# Client-side pacing
# --------------------------------------------------------------------------- #
class ChatRateLimiter:
    """Reserves send slots per (bot, chat) so bursts stay under Telegram limits.

    A slot is reserved without awaiting, so concurrent calls on one event loop
    never take the same slot. A call whose slot is too far away fails with a
    rate-limit error instead of holding the request open.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._slots: Dict[Tuple[str, str], Deque[float]] = {}

    def reserve(self, bot_key: str, chat_id: Any) -> float:
        """Reserve a slot and return how many seconds to wait for it."""
        now = self._clock()
        key = (bot_key, str(chat_id))
        slots = self._slots.setdefault(key, deque())
        while slots and slots[0] <= now - GROUP_WINDOW_SECONDS:
            slots.popleft()
        slot = now
        if slots:
            slot = max(slot, slots[-1] + PER_CHAT_INTERVAL_SECONDS)
        if is_group_chat(chat_id) and len(slots) >= GROUP_MAX_PER_WINDOW:
            slot = max(slot, slots[-GROUP_MAX_PER_WINDOW] + GROUP_WINDOW_SECONDS)
        wait = slot - now
        if wait > MAX_PACING_WAIT_SECONDS:
            raise TelegramError(
                RATE_LIMITED,
                "Too many messages to this chat. Retry after "
                f"{int(wait) + 1} seconds.",
                retry_after=int(wait) + 1,
            )
        slots.append(slot)
        return wait


def is_group_chat(chat_id: Any) -> bool:
    """Groups, supergroups and channels have negative IDs or a @username."""
    text = str(chat_id)
    return text.startswith("-") or text.startswith("@")


RATE_LIMITER = ChatRateLimiter()


# --------------------------------------------------------------------------- #
# Bot API client
# --------------------------------------------------------------------------- #
def create_http_client(timeout: httpx.Timeout = REQUEST_TIMEOUT) -> httpx.AsyncClient:
    """HTTP client for one tool call. Tests replace this with a mock transport."""
    return httpx.AsyncClient(timeout=timeout)


class BotAPI:
    def __init__(self, token: str, http: httpx.AsyncClient):
        self._token = token
        self._http = http
        self.bot_key = hashlib.sha256(token.encode()).hexdigest()[:16]

    def mask(self, text: Any) -> str:
        return mask_token(text, self._token)

    async def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Tuple[str, bytes, str]]] = None,
    ) -> Any:
        """Call a Bot API method and return its ``result``.

        A 429 with ``retry_after`` of at most ``MAX_RETRY_AFTER_SECONDS`` is
        retried once.
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in range(2):
            status, body = await self._post(method, params, files)
            if body.get("ok"):
                return body.get("result")
            error = error_from_response(status, body, self._token)
            retry_after = getattr(error, "details", {}).get("retry_after")
            if (
                attempt == 0
                and getattr(error, "code", None) == RATE_LIMITED
                and isinstance(retry_after, (int, float))
                and retry_after <= MAX_RETRY_AFTER_SECONDS
            ):
                logger.info(f"Telegram {method} rate limited; retrying once")
                await _sleep(retry_after)
                continue
            raise error
        raise error  # pragma: no cover - loop always returns or raises

    async def _post(
        self,
        method: str,
        params: Dict[str, Any],
        files: Optional[Dict[str, Tuple[str, bytes, str]]],
    ) -> Tuple[int, Dict[str, Any]]:
        url = f"{API_BASE}/bot{self._token}/{method}"
        try:
            if files:
                # Multipart: nested values (reply_markup, ...) go as JSON text.
                data = {
                    k: v if isinstance(v, str) else json.dumps(v)
                    for k, v in params.items()
                }
                response = await self._http.post(
                    url, data=data, files=files, timeout=UPLOAD_TIMEOUT
                )
            else:
                response = await self._http.post(url, json=params)
        except httpx.HTTPError as error:
            raise TelegramError(
                NETWORK_ERROR,
                f"Could not reach Telegram ({type(error).__name__}): "
                f"{self.mask(error)}",
            ) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if "ok" not in body:
            body = {
                "ok": False,
                "error_code": response.status_code,
                "description": response.reason_phrase,
            }
        return response.status_code, body

    async def download(self, file_path: str) -> bytes:
        url = f"{API_BASE}/file/bot{self._token}/{file_path}"
        try:
            response = await self._http.get(url, timeout=UPLOAD_TIMEOUT)
        except httpx.HTTPError as error:
            raise TelegramError(
                NETWORK_ERROR,
                f"Could not download the file ({type(error).__name__}): "
                f"{self.mask(error)}",
            ) from None
        if response.status_code == 401:
            raise CredentialError(SERVICE_NAME, REVOKED)
        if response.status_code != 200:
            raise TelegramError(
                API_ERROR,
                f"Telegram file download failed with HTTP {response.status_code}",
            )
        return response.content


# --------------------------------------------------------------------------- #
# Argument helpers
# --------------------------------------------------------------------------- #
def _chat_id(arguments: Dict[str, Any], field: str = "chat_id") -> Any:
    value = arguments.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is required")
    if text.lstrip("-").isdigit():
        return int(text)
    if text.startswith("https://t.me/") or text.startswith("t.me/"):
        text = "@" + text.rstrip("/").rsplit("/", 1)[-1]
    if not text.startswith("@"):
        text = "@" + text
    return text


def _int(arguments: Dict[str, Any], field: str, required: bool = True) -> Any:
    value = arguments.get(field)
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")


def _text(arguments: Dict[str, Any], field: str, limit: int) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} is longer than Telegram's {limit} characters")
    return value


def _caption(arguments: Dict[str, Any]) -> Optional[str]:
    caption = arguments.get("caption")
    if caption in (None, ""):
        return None
    if len(caption) > MAX_CAPTION_LENGTH:
        raise ValueError(
            f"caption is longer than Telegram's {MAX_CAPTION_LENGTH} characters"
        )
    return caption


def _parse_mode(arguments: Dict[str, Any]) -> Optional[str]:
    mode = arguments.get("parse_mode")
    if mode in (None, "", "none"):
        return None
    if mode not in ("HTML", "MarkdownV2"):
        raise ValueError("parse_mode must be one of: HTML, MarkdownV2, none")
    return mode


def _reply_markup(arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inline URL buttons: a list of rows, each a list of {text, url}."""
    rows = arguments.get("buttons")
    if not rows:
        return None
    if not isinstance(rows, list):
        raise ValueError("buttons must be a list of rows")
    keyboard = []
    for row in rows:
        if isinstance(row, dict):
            row = [row]
        if not isinstance(row, list) or not row:
            raise ValueError("each buttons row must be a non-empty list")
        buttons = []
        for button in row:
            text = button.get("text") if isinstance(button, dict) else None
            url = button.get("url") if isinstance(button, dict) else None
            if not text or not url:
                raise ValueError("each button needs text and url")
            if not str(url).startswith(("https://", "http://", "tg://")):
                raise ValueError(
                    "button url must start with https://, http:// or tg://"
                )
            buttons.append({"text": str(text), "url": str(url)})
        keyboard.append(buttons)
    return {"inline_keyboard": keyboard}


def _send_options(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Options shared by the send methods."""
    options: Dict[str, Any] = {
        "message_thread_id": _int(arguments, "message_thread_id", required=False),
        "reply_markup": _reply_markup(arguments),
    }
    if arguments.get("disable_notification"):
        options["disable_notification"] = True
    reply_to = _int(arguments, "reply_to_message_id", required=False)
    if reply_to is not None:
        options["reply_parameters"] = {
            "message_id": reply_to,
            "allow_sending_without_reply": True,
        }
    return options


def _decode_content(arguments: Dict[str, Any], max_bytes: int) -> bytes:
    try:
        content = base64.b64decode(arguments["content_base64"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ValueError("content_base64 must be valid base64")
    if not content:
        raise ValueError("content_base64 is empty")
    if len(content) > max_bytes:
        raise ValueError(
            f"File is {len(content)} bytes; Telegram bots can upload at most "
            f"{max_bytes // (1024 * 1024)} MB here"
        )
    return content


def _media_source(
    arguments: Dict[str, Any], field: str, max_bytes: int, default_name: str
) -> Tuple[Dict[str, Any], Optional[Dict[str, Tuple[str, bytes, str]]]]:
    """Return (params, files) for a file given by URL, file_id or base64."""
    url = arguments.get("file_url")
    file_id = arguments.get("file_id")
    has_content = bool(arguments.get("content_base64"))
    if sum(bool(x) for x in (url, file_id, has_content)) != 1:
        raise ValueError("Give exactly one of file_url, file_id or content_base64")
    if url:
        if not str(url).startswith(("https://", "http://")):
            raise ValueError("file_url must be an http(s) URL")
        return {field: str(url)}, None
    if file_id:
        return {field: str(file_id)}, None
    filename = str(arguments.get("filename") or default_name).strip()
    filename = os.path.basename(filename) or default_name
    content = _decode_content(arguments, max_bytes)
    mime = (
        arguments.get("mime_type")
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    return {}, {field: (filename, content, mime)}


# --------------------------------------------------------------------------- #
# Tool handlers
# --------------------------------------------------------------------------- #
Handler = Callable[[BotAPI, Dict[str, Any]], Awaitable[Any]]


async def _paced(api: BotAPI, chat_id: Any) -> None:
    wait = RATE_LIMITER.reserve(api.bot_key, chat_id)
    if wait > 0:
        await _sleep(wait)


async def get_bot_info(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    return await api.call("getMe")


async def get_chat(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    return await api.call("getChat", {"chat_id": _chat_id(arguments)})


async def get_chat_member_count(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    chat_id = _chat_id(arguments)
    count = await api.call("getChatMemberCount", {"chat_id": chat_id})
    return {"chat_id": chat_id, "member_count": count}


async def get_chat_administrators(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    return await api.call("getChatAdministrators", {"chat_id": _chat_id(arguments)})


async def send_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    chat_id = _chat_id(arguments)
    params = {
        "chat_id": chat_id,
        "text": _text(arguments, "text", MAX_TEXT_LENGTH),
        "parse_mode": _parse_mode(arguments),
        **_send_options(arguments),
    }
    if arguments.get("disable_link_preview"):
        params["link_preview_options"] = {"is_disabled": True}
    await _paced(api, chat_id)
    return await api.call("sendMessage", params)


async def _send_media(
    api: BotAPI,
    arguments: Dict[str, Any],
    method: str,
    field: str,
    max_bytes: int,
    default_name: str,
) -> Any:
    chat_id = _chat_id(arguments)
    source, files = _media_source(arguments, field, max_bytes, default_name)
    params = {
        "chat_id": chat_id,
        "caption": _caption(arguments),
        "parse_mode": _parse_mode(arguments),
        **_send_options(arguments),
        **source,
    }
    await _paced(api, chat_id)
    return await api.call(method, params, files=files)


async def send_document(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    return await _send_media(
        api,
        arguments,
        "sendDocument",
        "document",
        MAX_DOCUMENT_UPLOAD_BYTES,
        "document",
    )


async def send_photo(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    return await _send_media(
        api, arguments, "sendPhoto", "photo", MAX_PHOTO_UPLOAD_BYTES, "photo.jpg"
    )


async def edit_message_text(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    params = {
        "chat_id": _chat_id(arguments),
        "message_id": _int(arguments, "message_id"),
        "text": _text(arguments, "text", MAX_TEXT_LENGTH),
        "parse_mode": _parse_mode(arguments),
        "reply_markup": _reply_markup(arguments),
    }
    return await api.call("editMessageText", params)


async def delete_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    chat_id = _chat_id(arguments)
    message_id = _int(arguments, "message_id")
    deleted = await api.call(
        "deleteMessage", {"chat_id": chat_id, "message_id": message_id}
    )
    return {"chat_id": chat_id, "message_id": message_id, "deleted": bool(deleted)}


def _copy_params(arguments: Dict[str, Any]) -> Dict[str, Any]:
    params = {
        "chat_id": _chat_id(arguments),
        "from_chat_id": _chat_id(arguments, "from_chat_id"),
        "message_id": _int(arguments, "message_id"),
        "message_thread_id": _int(arguments, "message_thread_id", required=False),
    }
    if arguments.get("disable_notification"):
        params["disable_notification"] = True
    return params


async def forward_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    params = _copy_params(arguments)
    await _paced(api, params["chat_id"])
    return await api.call("forwardMessage", params)


async def copy_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    params = {
        **_copy_params(arguments),
        "caption": _caption(arguments),
        "parse_mode": _parse_mode(arguments),
        "reply_markup": _reply_markup(arguments),
    }
    await _paced(api, params["chat_id"])
    return await api.call("copyMessage", params)


async def pin_chat_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    params = {
        "chat_id": _chat_id(arguments),
        "message_id": _int(arguments, "message_id"),
    }
    if arguments.get("disable_notification"):
        params["disable_notification"] = True
    pinned = await api.call("pinChatMessage", params)
    return {**params, "pinned": bool(pinned)}


async def unpin_chat_message(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    params = {
        "chat_id": _chat_id(arguments),
        "message_id": _int(arguments, "message_id", required=False),
    }
    unpinned = await api.call("unpinChatMessage", params)
    return {**{k: v for k, v in params.items() if v is not None}, "unpinned": unpinned}


async def get_file(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    file_id = arguments.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        raise ValueError("file_id is required")
    return await api.call("getFile", {"file_id": file_id.strip()})


async def download_file(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    info = await get_file(api, arguments)
    size = info.get("file_size")
    if isinstance(size, int) and size > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"File is {size} bytes; Telegram bots can download at most 20 MB"
        )
    file_path = info.get("file_path")
    if not file_path:
        raise ValueError(
            "Telegram did not return a download path; the file may be larger "
            "than 20 MB"
        )
    content = await api.download(file_path)
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Downloaded file is larger than 20 MB")
    return {
        "file_id": info.get("file_id"),
        "file_unique_id": info.get("file_unique_id"),
        "file_size": len(content),
        "file_name": os.path.basename(file_path),
        "mime_type": mimetypes.guess_type(file_path)[0] or "application/octet-stream",
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


async def create_chat_invite_link(api: BotAPI, arguments: Dict[str, Any]) -> Any:
    member_limit = _int(arguments, "member_limit", required=False)
    if member_limit is not None and not 1 <= member_limit <= 99999:
        raise ValueError("member_limit must be between 1 and 99999")
    creates_join_request = bool(arguments.get("creates_join_request"))
    if creates_join_request and member_limit is not None:
        raise ValueError("member_limit cannot be used with creates_join_request")
    params = {
        "chat_id": _chat_id(arguments),
        "name": arguments.get("name") or None,
        "expire_date": _int(arguments, "expire_date", required=False),
        "member_limit": member_limit,
    }
    if creates_join_request:
        params["creates_join_request"] = True
    return await api.call("createChatInviteLink", params)


TOOL_HANDLERS: Dict[str, Handler] = {
    "get_bot_info": get_bot_info,
    "get_chat": get_chat,
    "get_chat_member_count": get_chat_member_count,
    "get_chat_administrators": get_chat_administrators,
    "send_message": send_message,
    "send_document": send_document,
    "send_photo": send_photo,
    "edit_message_text": edit_message_text,
    "delete_message": delete_message,
    "forward_message": forward_message,
    "copy_message": copy_message,
    "pin_chat_message": pin_chat_message,
    "unpin_chat_message": unpin_chat_message,
    "get_file": get_file,
    "download_file": download_file,
    "create_chat_invite_link": create_chat_invite_link,
}


# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #
def _chat_id_property(description: str = "Chat") -> Dict[str, Any]:
    return {
        "type": ["string", "integer"],
        "description": (
            f"{description}: a numeric chat ID (users are positive, groups and "
            "channels negative, for example -1001234567890) or a public "
            "@channelusername. The bot must already be in the chat, and a user "
            "must have pressed /start."
        ),
    }


_MESSAGE_ID = {"type": "integer", "description": "Message ID in the chat"}
_PARSE_MODE = {
    "type": "string",
    "enum": ["HTML", "MarkdownV2", "none"],
    "default": "none",
    "description": "Text formatting. MarkdownV2 needs special characters escaped",
}
_BUTTONS = {
    "type": "array",
    "description": "Inline URL buttons under the message: a list of rows",
    "items": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Button label"},
                "url": {"type": "string", "description": "https:// or tg:// link"},
            },
            "required": ["text", "url"],
        },
    },
}
_SEND_OPTIONS = {
    "reply_to_message_id": {
        "type": "integer",
        "description": "Reply to this message in the same chat",
    },
    "disable_notification": {
        "type": "boolean",
        "description": "Deliver silently",
    },
    "message_thread_id": {
        "type": "integer",
        "description": "Forum topic ID in a supergroup with topics",
    },
    "buttons": _BUTTONS,
}


def _media_properties(field: str, url_note: str) -> Dict[str, Any]:
    return {
        "chat_id": _chat_id_property("Chat to send to"),
        "file_url": {
            "type": "string",
            "description": f"Public http(s) URL Telegram downloads itself. {url_note}",
        },
        "file_id": {
            "type": "string",
            "description": f"file_id of a {field} Telegram already stores",
        },
        "content_base64": {
            "type": "string",
            "description": "File content, base64-encoded",
        },
        "filename": {
            "type": "string",
            "description": "File name shown in Telegram (with content_base64)",
        },
        "mime_type": {
            "type": "string",
            "description": "MIME type (with content_base64); guessed from filename",
        },
        "caption": {
            "type": "string",
            "description": f"Caption, up to {MAX_CAPTION_LENGTH} characters",
        },
        "parse_mode": _PARSE_MODE,
        **_SEND_OPTIONS,
    }


def tool_definitions() -> List[Tool]:
    return [
        Tool(
            name="get_bot_info",
            description="Get the connected bot's profile (getMe)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_chat",
            description="Get details of a chat, group or channel the bot is in",
            inputSchema={
                "type": "object",
                "properties": {"chat_id": _chat_id_property()},
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_chat_member_count",
            description="Count the members of a group or channel",
            inputSchema={
                "type": "object",
                "properties": {"chat_id": _chat_id_property("Group or channel")},
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_chat_administrators",
            description="List the administrators of a group or channel",
            inputSchema={
                "type": "object",
                "properties": {"chat_id": _chat_id_property("Group or channel")},
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="send_message",
            description="Send a text message from the bot",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Chat to send to"),
                    "text": {
                        "type": "string",
                        "description": f"Message text, up to {MAX_TEXT_LENGTH} "
                        "characters",
                    },
                    "parse_mode": _PARSE_MODE,
                    "disable_link_preview": {
                        "type": "boolean",
                        "description": "Do not show a link preview",
                    },
                    **_SEND_OPTIONS,
                },
                "required": ["chat_id", "text"],
            },
        ),
        Tool(
            name="send_document",
            description=(
                "Send a file. Give exactly one of file_url, file_id or "
                "content_base64 (+ filename). Uploads are limited to 50 MB"
            ),
            inputSchema={
                "type": "object",
                "properties": _media_properties(
                    "document",
                    "By URL Telegram only accepts PDF, ZIP and GIF files up to "
                    "20 MB; use content_base64 for other files",
                ),
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="send_photo",
            description=(
                "Send a photo. Give exactly one of file_url, file_id or "
                "content_base64. Uploads are limited to 10 MB"
            ),
            inputSchema={
                "type": "object",
                "properties": _media_properties(
                    "photo", "Telegram accepts photos up to 5 MB by URL"
                ),
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="edit_message_text",
            description="Edit the text (and buttons) of a message the bot sent",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_id": _MESSAGE_ID,
                    "text": {"type": "string", "description": "New message text"},
                    "parse_mode": _PARSE_MODE,
                    "buttons": _BUTTONS,
                },
                "required": ["chat_id", "message_id", "text"],
            },
        ),
        Tool(
            name="delete_message",
            description=(
                "Delete a message. Bots can delete their own messages, and other "
                "messages in groups where they are admins, within 48 hours"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_id": _MESSAGE_ID,
                },
                "required": ["chat_id", "message_id"],
            },
        ),
        Tool(
            name="forward_message",
            description="Forward a message to another chat, showing its origin",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Chat to forward to"),
                    "from_chat_id": _chat_id_property("Chat the message is in"),
                    "message_id": _MESSAGE_ID,
                    "disable_notification": _SEND_OPTIONS["disable_notification"],
                    "message_thread_id": _SEND_OPTIONS["message_thread_id"],
                },
                "required": ["chat_id", "from_chat_id", "message_id"],
            },
        ),
        Tool(
            name="copy_message",
            description=(
                "Copy a message to another chat without the forward header, "
                "optionally with a new caption"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Chat to copy to"),
                    "from_chat_id": _chat_id_property("Chat the message is in"),
                    "message_id": _MESSAGE_ID,
                    "caption": {
                        "type": "string",
                        "description": "New caption for media messages",
                    },
                    "parse_mode": _PARSE_MODE,
                    "disable_notification": _SEND_OPTIONS["disable_notification"],
                    "message_thread_id": _SEND_OPTIONS["message_thread_id"],
                    "buttons": _BUTTONS,
                },
                "required": ["chat_id", "from_chat_id", "message_id"],
            },
        ),
        Tool(
            name="pin_chat_message",
            description="Pin a message (the bot needs the pin right in groups)",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_id": _MESSAGE_ID,
                    "disable_notification": {
                        "type": "boolean",
                        "description": "Pin without notifying members",
                    },
                },
                "required": ["chat_id", "message_id"],
            },
        ),
        Tool(
            name="unpin_chat_message",
            description="Unpin a message, or the most recent pin if no message_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property(),
                    "message_id": _MESSAGE_ID,
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_file",
            description="Get metadata (size, path) of a file by its file_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "file_id from a message or webhook update",
                    }
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="download_file",
            description=(
                "Download a file by its file_id and return it base64-encoded "
                "(Telegram bots can download at most 20 MB)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "file_id from a message or webhook update",
                    }
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="create_chat_invite_link",
            description="Create an invite link for a group or channel (bot is admin)",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": _chat_id_property("Group or channel"),
                    "name": {"type": "string", "description": "Link name"},
                    "expire_date": {
                        "type": "integer",
                        "description": "Unix timestamp when the link expires",
                    },
                    "member_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 99999,
                        "description": "How many people can join with the link",
                    },
                    "creates_join_request": {
                        "type": "boolean",
                        "description": "Admins must approve people who join",
                    },
                },
                "required": ["chat_id"],
            },
        ),
    ]


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #
async def execute_tool(
    user_id: str, name: str, arguments: Dict[str, Any], api_key: Optional[str] = None
) -> Tuple[Any, str]:
    """Run a tool and return ``(result, token)`` so the caller can mask output."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    async with create_http_client() as http:
        api = BotAPI(token, http)
        try:
            return await handler(api, arguments), token
        except (CredentialError, TelegramError):
            raise
        except ValueError as error:
            raise ValueError(api.mask(error)) from None
        except Exception as error:
            logger.error(f"Telegram tool {name} failed: {type(error).__name__}")
            raise ValueError(
                f"Telegram tool failed: {api.mask(error) or type(error).__name__}"
            ) from None


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
        result, token = await execute_tool(
            server.user_id, name, arguments or {}, api_key=server.api_key
        )
        text = json.dumps(result, default=str, ensure_ascii=False)
        return [TextContent(type="text", text=mask_token(text, token))]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="telegram-server",
        server_version="2.0.0",
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
        print("  python main.py auth - Save a Telegram bot token for local use")
        print("Note: To run the server normally, use the pfMCP server framework.")
