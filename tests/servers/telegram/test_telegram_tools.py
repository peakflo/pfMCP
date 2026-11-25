"""Network-free tests for the Telegram Bot API server.

httpx runs on a ``MockTransport`` that records every request, so the tests see
the exact Bot API method, URL and body without touching the network.
"""

import base64
import json
import logging
from typing import Any, Callable, Dict, List
from unittest import mock

import httpx
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

# The server module puts src/ on sys.path, which the auth imports need.
from src.servers.telegram import main
from src.utils.telegram import util
from src.auth.constants import AUTH_TYPE_API_KEY, SERVICE_NAME_MAP
from src.auth.credential_errors import MISSING, REVOKED, SETUP_INCOMPLETE

TOKEN = "123456789:AAEhBP0av28Rk-9ka_mSecretTokenValue42"


def ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def fail(code: int, description: str, **parameters) -> Dict[str, Any]:
    body = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return body


class FakeTelegram:
    """Answers Bot API calls from a queue and records each request."""

    def __init__(self, *answers, files: Dict[str, bytes] = None):
        self.answers: List[Any] = list(answers)
        self.files = files or {}
        self.requests: List[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.startswith(f"/file/bot{TOKEN}/"):
            name = path.split("/", 3)[3]
            if name in self.files:
                return httpx.Response(200, content=self.files[name])
            return httpx.Response(404)
        answer = self.answers.pop(0) if self.answers else ok(True)
        if isinstance(answer, Exception):
            raise answer
        status = 200 if answer.get("ok") else answer.get("error_code", 500)
        return httpx.Response(status, json=answer)

    def client(self, timeout=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    # Helpers for assertions -------------------------------------------------
    def method(self, index: int = -1) -> str:
        return self.requests[index].url.path.rsplit("/", 1)[-1]

    def body(self, index: int = -1) -> Dict[str, Any]:
        return json.loads(self.requests[index].content)


@pytest.fixture(autouse=True)
def fresh_limiter():
    with (
        mock.patch.object(main, "RATE_LIMITER", main.ChatRateLimiter()),
        mock.patch.object(main, "_sleep", new_callable=mock.AsyncMock) as sleep,
    ):
        yield sleep


async def call(name: str, arguments: Dict[str, Any], fake: FakeTelegram):
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    with (
        mock.patch.object(
            main, "get_credentials", new_callable=mock.AsyncMock, return_value=TOKEN
        ),
        mock.patch.object(main, "create_http_client", fake.client),
    ):
        result = await server.dispatch(request)
    text = result.content[0].text
    assert TOKEN not in text
    assert TOKEN.split(":")[1] not in text
    if result.is_error:
        return result, text
    return result, json.loads(text)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
EXPECTED_TOOLS = {
    "get_bot_info",
    "get_chat",
    "get_chat_member_count",
    "get_chat_administrators",
    "send_message",
    "send_document",
    "send_photo",
    "edit_message_text",
    "delete_message",
    "forward_message",
    "copy_message",
    "pin_chat_message",
    "unpin_chat_message",
    "get_file",
    "download_file",
    "create_chat_invite_link",
}


def test_service_is_mapped_to_nango_api_key():
    assert SERVICE_NAME_MAP["telegram"] == {
        "nango_service_name": "telegram",
        "auth_type": AUTH_TYPE_API_KEY,
    }


async def test_tools_are_listed_and_get_updates_is_not():
    result = await main.create_server("connection-1").dispatch(
        ListToolsRequest(method="tools/list")
    )
    names = {tool.name for tool in result.tools}
    assert names == EXPECTED_TOOLS == set(main.TOOL_HANDLERS)
    assert "get_updates" not in names
    assert all(tool.input_schema["type"] == "object" for tool in result.tools)


def test_config_yaml_lists_the_same_tools():
    import yaml
    from pathlib import Path

    config = yaml.safe_load(
        (Path(main.__file__).parent / "config.yaml").read_text(encoding="utf-8")
    )
    assert {tool["name"] for tool in config["tools"]} == EXPECTED_TOOLS


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def test_token_is_read_from_nango_api_key():
    assert util.parse_bot_token({"apiKey": f"  {TOKEN} "}) == TOKEN


@pytest.mark.parametrize("payload", [None, {}, {"apiKey": ""}, {"other": "x"}])
def test_missing_token_is_credentials_missing(payload):
    with pytest.raises(ValueError) as error:
        util.parse_bot_token(payload)
    assert error.value.code == MISSING
    assert str(error.value).startswith(f"[{MISSING}]")


def test_malformed_token_is_setup_incomplete_and_not_echoed():
    with pytest.raises(ValueError) as error:
        util.parse_bot_token({"apiKey": "not a token"})
    assert error.value.code == SETUP_INCOMPLETE
    assert "not a token" not in str(error.value)


async def test_get_credentials_uses_auth_client():
    client = mock.MagicMock(spec=["get_user_credentials"])
    client.get_user_credentials.return_value = {"apiKey": TOKEN}
    with mock.patch.object(util, "create_auth_client", return_value=client):
        assert await util.get_credentials("u", "telegram", api_key="k") == TOKEN
    client.get_user_credentials.assert_called_once_with("telegram", "u")


async def test_get_credentials_without_connection_is_missing():
    client = mock.MagicMock(spec=["get_user_credentials"])
    client.get_user_credentials.return_value = None
    with mock.patch.object(util, "create_auth_client", return_value=client):
        with pytest.raises(ValueError) as error:
            await util.get_credentials("u", "telegram")
    assert error.value.code == MISSING


# --------------------------------------------------------------------------- #
# Token masking
# --------------------------------------------------------------------------- #
def test_mask_token_removes_token_and_token_shaped_text():
    text = f"POST https://api.telegram.org/bot{TOKEN}/sendMessage and {TOKEN}"
    masked = util.mask_token(text, TOKEN)
    assert TOKEN not in masked
    assert masked.count(util.MASK) == 2
    # Without knowing the token, token-shaped values are still masked.
    assert TOKEN not in util.mask_token(text)


def test_httpx_request_logs_are_masked(caplog):
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        'HTTP Request: %s %s "%s"',
        ("POST", f"https://api.telegram.org/bot{TOKEN}/getMe", "HTTP/1.1 200 OK"),
        None,
    )
    assert any(
        isinstance(f, util.TokenMaskingFilter)
        for f in logging.getLogger("httpx").filters
    )
    for log_filter in logging.getLogger("httpx").filters:
        log_filter.filter(record)
    assert TOKEN not in record.getMessage()
    assert util.MASK in record.getMessage()


async def test_token_in_telegram_description_is_masked():
    fake = FakeTelegram(fail(400, f"Bad Request: weird {TOKEN} echo"))
    result, text = await call("get_chat", {"chat_id": 1}, fake)
    assert result.is_error
    assert "[telegram_bad_request]" in text


async def test_network_error_does_not_leak_url():
    fake = FakeTelegram(
        httpx.ConnectError(f"failed https://api.telegram.org/bot{TOKEN}/getMe")
    )
    result, text = await call("get_bot_info", {}, fake)
    assert result.is_error
    assert "[telegram_unreachable]" in text


async def test_request_url_uses_token_path():
    fake = FakeTelegram(ok({"id": 1, "is_bot": True, "username": "pf_bot"}))
    _, data = await call("get_bot_info", {}, fake)
    assert data["username"] == "pf_bot"
    assert str(fake.requests[0].url) == f"https://api.telegram.org/bot{TOKEN}/getMe"
    assert fake.requests[0].method == "POST"


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #
async def test_401_is_credentials_revoked():
    fake = FakeTelegram(fail(401, "Unauthorized"))
    result, text = await call("get_bot_info", {}, fake)
    assert result.is_error
    assert text.startswith(f"[{REVOKED}]")


async def test_404_not_found_method_is_credentials_revoked():
    fake = FakeTelegram(fail(404, "Not Found"))
    _, text = await call("get_bot_info", {}, fake)
    assert text.startswith(f"[{REVOKED}]")


async def test_403_is_forbidden_with_hint():
    fake = FakeTelegram(fail(403, "Forbidden: bot was blocked by the user"))
    result, text = await call("send_message", {"chat_id": 5, "text": "hi"}, fake)
    assert result.is_error
    assert text.startswith("[telegram_forbidden]")
    assert "blocked by the user" in text
    assert "/start" in text


async def test_400_is_bad_request_with_migrate_hint():
    fake = FakeTelegram(
        fail(
            400,
            "Bad Request: group chat was upgraded to a supergroup chat",
            migrate_to_chat_id=-1001234,
        )
    )
    _, text = await call("send_message", {"chat_id": -55, "text": "hi"}, fake)
    assert text.startswith("[telegram_bad_request]")
    assert "-1001234" in text


async def test_429_short_retry_after_is_retried_once(fresh_limiter):
    fake = FakeTelegram(
        fail(429, "Too Many Requests: retry after 3", retry_after=3),
        ok({"message_id": 9}),
    )
    _, data = await call("send_message", {"chat_id": 5, "text": "hi"}, fake)
    assert data == {"message_id": 9}
    assert len(fake.requests) == 2
    fresh_limiter.assert_any_await(3)


async def test_429_twice_reports_retry_after():
    fake = FakeTelegram(
        fail(429, "Too Many Requests", retry_after=2),
        fail(429, "Too Many Requests", retry_after=2),
    )
    _, text = await call("send_message", {"chat_id": 5, "text": "hi"}, fake)
    assert text.startswith("[telegram_rate_limited]")
    assert "2 seconds" in text
    assert len(fake.requests) == 2


async def test_429_long_retry_after_is_not_retried():
    fake = FakeTelegram(fail(429, "Too Many Requests", retry_after=40))
    _, text = await call("send_message", {"chat_id": 5, "text": "hi"}, fake)
    assert text.startswith("[telegram_rate_limited]")
    assert "40 seconds" in text
    assert len(fake.requests) == 1


async def test_non_json_error_is_reported():
    fake = FakeTelegram()
    fake.handler = lambda request: (
        fake.requests.append(request) or httpx.Response(502, text="<html>")
    )
    _, text = await call("get_bot_info", {}, fake)
    assert text.startswith("[telegram_error]")
    assert "502" in text


# --------------------------------------------------------------------------- #
# Client-side pacing
# --------------------------------------------------------------------------- #
def make_limiter(now: List[float]) -> main.ChatRateLimiter:
    return main.ChatRateLimiter(clock=lambda: now[0])


def test_pacing_spaces_messages_per_chat():
    now = [100.0]
    limiter = make_limiter(now)
    assert limiter.reserve("bot", 5) == 0
    assert limiter.reserve("bot", 5) == pytest.approx(1.0)
    assert limiter.reserve("bot", 6) == 0  # another chat is independent
    assert limiter.reserve("other-bot", 5) == 0  # another bot is independent


def test_pacing_limits_groups_per_minute():
    now = [0.0]
    limiter = make_limiter(now)
    for i in range(20):
        now[0] = i * 2.0
        assert limiter.reserve("bot", -100) == 0
    now[0] = 40.0
    with pytest.raises(ValueError) as error:
        limiter.reserve("bot", -100)
    assert str(error.value).startswith("[telegram_rate_limited]")
    now[0] = 59.0
    assert limiter.reserve("bot", -100) == pytest.approx(1.0)


def test_pacing_fails_fast_when_backlog_is_long():
    limiter = make_limiter([0.0])
    for _ in range(6):
        limiter.reserve("bot", 5)
    with pytest.raises(ValueError):
        limiter.reserve("bot", 5)


async def test_send_waits_for_pacing_slot(fresh_limiter):
    fake = FakeTelegram(ok({"message_id": 1}), ok({"message_id": 2}))
    await call("send_message", {"chat_id": 5, "text": "a"}, fake)
    await call("send_message", {"chat_id": 5, "text": "b"}, fake)
    assert fresh_limiter.await_count == 1
    assert fresh_limiter.await_args.args[0] == pytest.approx(1.0, abs=0.2)


# --------------------------------------------------------------------------- #
# Request shapes
# --------------------------------------------------------------------------- #
async def test_get_chat_and_counts():
    fake = FakeTelegram(
        ok({"id": -100, "type": "supergroup", "title": "Finance"}),
        ok(42),
        ok([{"status": "creator", "user": {"id": 1}}]),
    )
    _, chat = await call("get_chat", {"chat_id": "-100"}, fake)
    assert chat["title"] == "Finance"
    assert (fake.method(0), fake.body(0)) == ("getChat", {"chat_id": -100})

    _, count = await call("get_chat_member_count", {"chat_id": "@finance"}, fake)
    assert count == {"chat_id": "@finance", "member_count": 42}
    assert fake.method(1) == "getChatMemberCount"

    _, admins = await call("get_chat_administrators", {"chat_id": -100}, fake)
    assert admins[0]["status"] == "creator"
    assert fake.method(2) == "getChatAdministrators"


async def test_chat_id_accepts_t_me_link():
    fake = FakeTelegram(ok({"id": -1}))
    await call("get_chat", {"chat_id": "https://t.me/finance_news"}, fake)
    assert fake.body()["chat_id"] == "@finance_news"


async def test_send_message_full_options():
    fake = FakeTelegram(ok({"message_id": 77}))
    _, data = await call(
        "send_message",
        {
            "chat_id": -100123,
            "text": "<b>Invoice</b> ready",
            "parse_mode": "HTML",
            "reply_to_message_id": 10,
            "disable_notification": True,
            "message_thread_id": 4,
            "disable_link_preview": True,
            "buttons": [[{"text": "Open", "url": "https://app.peakflo.co/x"}]],
        },
        fake,
    )
    assert data == {"message_id": 77}
    assert fake.method() == "sendMessage"
    assert fake.body() == {
        "chat_id": -100123,
        "text": "<b>Invoice</b> ready",
        "parse_mode": "HTML",
        "message_thread_id": 4,
        "reply_markup": {
            "inline_keyboard": [[{"text": "Open", "url": "https://app.peakflo.co/x"}]]
        },
        "disable_notification": True,
        "reply_parameters": {"message_id": 10, "allow_sending_without_reply": True},
        "link_preview_options": {"is_disabled": True},
    }


async def test_send_message_minimal_omits_empty_fields():
    fake = FakeTelegram(ok({"message_id": 1}))
    await call("send_message", {"chat_id": "5", "text": "hi"}, fake)
    assert fake.body() == {"chat_id": 5, "text": "hi"}


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"chat_id": 5, "text": "x" * 4097}, "4096"),
        ({"chat_id": 5, "text": "hi", "parse_mode": "Markdown"}, "Markdown"),
        (
            {
                "chat_id": 5,
                "text": "hi",
                "buttons": [[{"text": "a", "url": "ftp://x"}]],
            },
            "url",
        ),
    ],
)
async def test_send_message_validation(arguments, message):
    fake = FakeTelegram()
    result, text = await call("send_message", arguments, fake)
    assert result.is_error
    assert message in text
    assert fake.requests == []


async def test_send_document_by_url():
    fake = FakeTelegram(ok({"message_id": 3}))
    await call(
        "send_document",
        {
            "chat_id": 5,
            "file_url": "https://example.com/invoice.pdf",
            "caption": "Invoice",
        },
        fake,
    )
    assert fake.method() == "sendDocument"
    assert fake.body() == {
        "chat_id": 5,
        "caption": "Invoice",
        "document": "https://example.com/invoice.pdf",
    }


async def test_send_document_from_base64_is_multipart():
    content = b"%PDF-1.4 test"
    fake = FakeTelegram(ok({"message_id": 4}))
    await call(
        "send_document",
        {
            "chat_id": 5,
            "content_base64": base64.b64encode(content).decode(),
            "filename": "../../invoice.pdf",
            "caption": "Inv",
            "buttons": [[{"text": "Pay", "url": "https://pay.example"}]],
        },
        fake,
    )
    request = fake.requests[-1]
    assert request.url.path.endswith("/sendDocument")
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert content in body
    assert b'filename="invoice.pdf"' in body
    assert b"application/pdf" in body
    assert b'name="chat_id"' in body
    assert b'"inline_keyboard"' in body


@pytest.mark.parametrize(
    "arguments",
    [
        {"chat_id": 5},
        {"chat_id": 5, "file_url": "https://x/a.pdf", "file_id": "abc"},
        {"chat_id": 5, "content_base64": "not base64!!"},
        {"chat_id": 5, "file_url": "file:///etc/passwd"},
    ],
)
async def test_send_document_rejects_bad_sources(arguments):
    fake = FakeTelegram()
    result, _ = await call("send_document", arguments, fake)
    assert result.is_error
    assert fake.requests == []


async def test_send_document_rejects_oversized_upload():
    big = base64.b64encode(b"0" * (main.MAX_PHOTO_UPLOAD_BYTES + 1)).decode()
    fake = FakeTelegram()
    result, text = await call("send_photo", {"chat_id": 5, "content_base64": big}, fake)
    assert result.is_error
    assert "10 MB" in text


async def test_send_photo_by_file_id():
    fake = FakeTelegram(ok({"message_id": 5}))
    await call(
        "send_photo",
        {"chat_id": 5, "file_id": "AgAC123", "disable_notification": True},
        fake,
    )
    assert fake.method() == "sendPhoto"
    assert fake.body() == {
        "chat_id": 5,
        "photo": "AgAC123",
        "disable_notification": True,
    }


async def test_edit_message_text():
    fake = FakeTelegram(ok({"message_id": 8, "text": "new"}))
    await call(
        "edit_message_text",
        {"chat_id": 5, "message_id": 8, "text": "new", "parse_mode": "MarkdownV2"},
        fake,
    )
    assert fake.method() == "editMessageText"
    assert fake.body() == {
        "chat_id": 5,
        "message_id": 8,
        "text": "new",
        "parse_mode": "MarkdownV2",
    }


async def test_delete_message():
    fake = FakeTelegram(ok(True))
    _, data = await call("delete_message", {"chat_id": 5, "message_id": 8}, fake)
    assert data == {"chat_id": 5, "message_id": 8, "deleted": True}
    assert fake.method() == "deleteMessage"
    assert fake.body() == {"chat_id": 5, "message_id": 8}


async def test_forward_and_copy_message():
    fake = FakeTelegram(ok({"message_id": 20}), ok({"message_id": 21}))
    await call(
        "forward_message",
        {"chat_id": -100, "from_chat_id": 5, "message_id": 8, "message_thread_id": 2},
        fake,
    )
    assert fake.method(0) == "forwardMessage"
    assert fake.body(0) == {
        "chat_id": -100,
        "from_chat_id": 5,
        "message_id": 8,
        "message_thread_id": 2,
    }
    await call(
        "copy_message",
        {"chat_id": -100, "from_chat_id": 5, "message_id": 8, "caption": "fyi"},
        fake,
    )
    assert fake.method(1) == "copyMessage"
    assert fake.body(1) == {
        "chat_id": -100,
        "from_chat_id": 5,
        "message_id": 8,
        "caption": "fyi",
    }


async def test_pin_and_unpin():
    fake = FakeTelegram(ok(True), ok(True), ok(True))
    _, pinned = await call(
        "pin_chat_message",
        {"chat_id": -100, "message_id": 8, "disable_notification": True},
        fake,
    )
    assert pinned["pinned"] is True
    assert fake.method(0) == "pinChatMessage"
    assert fake.body(0) == {
        "chat_id": -100,
        "message_id": 8,
        "disable_notification": True,
    }
    await call("unpin_chat_message", {"chat_id": -100, "message_id": 8}, fake)
    assert (fake.method(1), fake.body(1)) == (
        "unpinChatMessage",
        {"chat_id": -100, "message_id": 8},
    )
    await call("unpin_chat_message", {"chat_id": -100}, fake)
    assert fake.body(2) == {"chat_id": -100}


async def test_get_file_metadata():
    info = {"file_id": "F1", "file_unique_id": "U1", "file_size": 3, "file_path": "a"}
    fake = FakeTelegram(ok(info))
    _, data = await call("get_file", {"file_id": "F1"}, fake)
    assert data == info
    assert (fake.method(), fake.body()) == ("getFile", {"file_id": "F1"})


async def test_download_file_returns_base64():
    content = b"%PDF-1.4 hello"
    fake = FakeTelegram(
        ok(
            {
                "file_id": "F1",
                "file_unique_id": "U1",
                "file_size": len(content),
                "file_path": "documents/file_1.pdf",
            }
        ),
        files={"documents/file_1.pdf": content},
    )
    _, data = await call("download_file", {"file_id": "F1"}, fake)
    assert data == {
        "file_id": "F1",
        "file_unique_id": "U1",
        "file_size": len(content),
        "file_name": "file_1.pdf",
        "mime_type": "application/pdf",
        "content_base64": base64.b64encode(content).decode(),
    }
    assert str(fake.requests[1].url) == (
        f"https://api.telegram.org/file/bot{TOKEN}/documents/file_1.pdf"
    )


async def test_download_file_over_20_mb_is_refused():
    fake = FakeTelegram(ok({"file_id": "F1", "file_size": main.MAX_DOWNLOAD_BYTES + 1}))
    result, text = await call("download_file", {"file_id": "F1"}, fake)
    assert result.is_error
    assert "20 MB" in text
    assert len(fake.requests) == 1


async def test_create_chat_invite_link():
    fake = FakeTelegram(ok({"invite_link": "https://t.me/+abc"}))
    _, data = await call(
        "create_chat_invite_link",
        {
            "chat_id": -100,
            "name": "Vendors",
            "expire_date": 1900000000,
            "member_limit": 5,
        },
        fake,
    )
    assert data["invite_link"] == "https://t.me/+abc"
    assert fake.method() == "createChatInviteLink"
    assert fake.body() == {
        "chat_id": -100,
        "name": "Vendors",
        "expire_date": 1900000000,
        "member_limit": 5,
    }


async def test_invite_link_rejects_limit_with_join_request():
    fake = FakeTelegram()
    result, _ = await call(
        "create_chat_invite_link",
        {"chat_id": -100, "member_limit": 5, "creates_join_request": True},
        fake,
    )
    assert result.is_error
    assert fake.requests == []


async def test_unknown_tool_is_an_error():
    fake = FakeTelegram()
    result, text = await call("get_updates", {}, fake)
    assert result.is_error
    assert fake.requests == []


def test_handlers_are_callables():
    for handler in main.TOOL_HANDLERS.values():
        assert isinstance(handler, Callable)
