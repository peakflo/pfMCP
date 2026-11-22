"""Network-free tests for the Telegram server: credentials, Nango mapping and tools.

Telethon is never connected; the client is a mock and the entities are real
Telethon TL objects so formatting runs against the real types.
"""

import json
from datetime import datetime, timezone
from unittest import mock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest
from telethon import errors, types

# The server module puts src/ on sys.path, which NangoAuthClient needs.
from src.servers.telegram import main
from src.utils.telegram import util
from src.auth.clients.NangoAuthClient import NangoAuthClient
from src.auth.constants import AUTH_TYPE_API_KEY, SERVICE_NAME_MAP
from src.auth.credential_errors import MISSING, REVOKED, SETUP_INCOMPLETE

DATE = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
CREDENTIALS = {"api_id": 12345, "api_hash": "hash", "session_string": "session"}


def user(user_id=42, **kwargs):
    defaults = {"first_name": "Ada", "last_name": "Lovelace", "username": "ada"}
    defaults.update(kwargs)
    return types.User(id=user_id, **defaults)


def supergroup(channel_id=777, **kwargs):
    return types.Channel(
        id=channel_id,
        title="Finance Team",
        photo=types.ChatPhotoEmpty(),
        date=DATE,
        megagroup=True,
        username="finance_team",
        **kwargs,
    )


def message(message_id=10, text="hello", peer=None, sender=None, **kwargs):
    return types.Message(
        id=message_id,
        peer_id=peer or types.PeerUser(42),
        date=DATE,
        message=text,
        from_id=sender,
        **kwargs,
    )


def fake_client():
    client = mock.MagicMock()
    for name in (
        "connect",
        "disconnect",
        "is_user_authorized",
        "get_me",
        "get_entity",
        "get_dialogs",
        "get_messages",
        "send_message",
        "edit_message",
        "delete_messages",
        "forward_messages",
        "send_read_acknowledge",
        "get_participants",
    ):
        setattr(client, name, mock.AsyncMock())
    client.is_user_authorized.return_value = True
    # Raw TL calls such as client(GetContactsRequest(...)) go through
    # client.side_effect, which each test sets when it needs one.
    return client


async def call(name, arguments, client):
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    with (
        mock.patch.object(
            main,
            "get_credentials",
            new_callable=mock.AsyncMock,
            return_value=CREDENTIALS,
        ),
        mock.patch.object(main, "create_telegram_client", return_value=client),
    ):
        result = await server.dispatch(request)
    text = result.content[0].text
    if result.is_error:
        return result, text
    return result, json.loads(text)


# --------------------------------------------------------------------------- #
# Registration and credentials
# --------------------------------------------------------------------------- #
def test_service_is_mapped_to_nango_api_key():
    assert SERVICE_NAME_MAP["telegram"] == {
        "nango_service_name": "telegram",
        "auth_type": AUTH_TYPE_API_KEY,
    }


async def test_tools_are_listed():
    result = await main.create_server("connection-1").dispatch(
        ListToolsRequest(method="tools/list")
    )
    names = {tool.name for tool in result.tools}
    assert names == set(main.TOOL_HANDLERS)
    assert {
        "get_me",
        "list_chats",
        "get_chat",
        "get_messages",
        "search_messages",
        "send_message",
        "edit_message",
        "delete_messages",
        "forward_messages",
        "mark_as_read",
        "list_contacts",
        "get_user",
        "resolve_username",
        "get_participants",
    } == names
    assert all(tool.input_schema["type"] == "object" for tool in result.tools)


def test_parse_credentials_from_nango_api_key_and_connection_config():
    parsed = util.parse_credentials(
        {
            "type": "API_KEY",
            "apiKey": "session-string",
            "connection_config": {"api_id": "12345", "api_hash": "abc"},
            "metadata": {},
        }
    )
    assert parsed == {
        "api_id": 12345,
        "api_hash": "abc",
        "session_string": "session-string",
    }


def test_parse_credentials_from_metadata_camel_case():
    parsed = util.parse_credentials(
        {"apiKey": "s", "metadata": {"apiId": 7, "apiHash": "h"}}
    )
    assert parsed == {"api_id": 7, "api_hash": "h", "session_string": "s"}


def test_parse_credentials_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "999")
    monkeypatch.setenv("TELEGRAM_API_HASH", "envhash")
    parsed = util.parse_credentials({"apiKey": "s"})
    assert parsed == {"api_id": 999, "api_hash": "envhash", "session_string": "s"}


def test_parse_credentials_from_local_store():
    assert util.parse_credentials(CREDENTIALS) == CREDENTIALS


def test_session_string_is_never_read_from_metadata(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    with pytest.raises(util.CredentialError) as raised:
        util.parse_credentials(
            {"metadata": {"session_string": "s", "api_id": 1, "api_hash": "h"}}
        )
    assert raised.value.code == MISSING


@pytest.mark.parametrize(
    "payload",
    [
        {"apiKey": "secret-session", "connection_config": {"api_hash": "h"}},
        {
            "apiKey": "secret-session",
            "connection_config": {"api_id": "x", "api_hash": "h"},
        },
    ],
)
def test_parse_credentials_reports_incomplete_setup(monkeypatch, payload):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    with pytest.raises(util.CredentialError) as raised:
        util.parse_credentials(payload)
    assert raised.value.code == SETUP_INCOMPLETE
    assert "secret-session" not in str(raised.value)


def test_parse_credentials_missing():
    with pytest.raises(util.CredentialError) as raised:
        util.parse_credentials(None)
    assert raised.value.code == MISSING


async def test_get_credentials_reports_recorded_nango_failure():
    auth_client = mock.Mock()
    auth_client.async_get_user_credentials = mock.AsyncMock(return_value=None)
    with (
        mock.patch.object(util, "create_auth_client", return_value=auth_client),
        mock.patch.object(util, "credential_error_from_last") as from_last,
    ):
        from_last.return_value = util.CredentialError("telegram", REVOKED)
        with pytest.raises(util.CredentialError) as raised:
            await util.get_credentials("connection-1", "telegram")
    assert raised.value.code == REVOKED
    from_last.assert_called_once_with("telegram")


async def test_nango_api_key_connection_keeps_connection_config():
    client = NangoAuthClient(secret_key="secret", host="https://nango.test")
    NangoAuthClient._cache.clear()
    response = mock.Mock()
    response.json.return_value = {
        "credentials": {"type": "API_KEY", "apiKey": "session-string"},
        "connection_config": {"api_id": "12345", "api_hash": "abc"},
        "metadata": {"note": "x"},
    }
    with mock.patch.object(
        client, "_async_fetch_connection_with_retries", return_value=response
    ):
        credentials = await client.async_get_user_credentials("telegram", "conn-1")
    NangoAuthClient._cache.clear()

    assert credentials["apiKey"] == "session-string"
    assert credentials["connection_config"] == {"api_id": "12345", "api_hash": "abc"}
    assert util.parse_credentials(credentials) == {
        "api_id": 12345,
        "api_hash": "abc",
        "session_string": "session-string",
    }


# --------------------------------------------------------------------------- #
# Connection handling
# --------------------------------------------------------------------------- #
async def test_unauthorized_session_is_reported_as_revoked():
    client = fake_client()
    client.is_user_authorized.return_value = False
    result, text = await call("get_me", {}, client)
    assert result.is_error
    assert "[credentials_revoked]" in text
    client.disconnect.assert_awaited()


async def test_revoked_session_error_during_tool():
    client = fake_client()
    client.get_me.side_effect = errors.AuthKeyUnregisteredError(request=None)
    result, text = await call("get_me", {}, client)
    assert result.is_error
    assert "[credentials_revoked]" in text
    client.disconnect.assert_awaited_once()


async def test_flood_wait_is_reported():
    client = fake_client()
    client.get_dialogs.side_effect = errors.FloodWaitError(request=None, capture=30)
    result, text = await call("list_chats", {}, client)
    assert result.is_error
    assert "30 seconds" in text
    client.disconnect.assert_awaited_once()


async def test_client_never_logs_in_interactively():
    client = fake_client()
    client.get_me.return_value = user()
    await call("get_me", {}, client)
    client.connect.assert_awaited_once()
    assert not client.start.called
    assert not client.sign_in.called
    client.disconnect.assert_awaited_once()


def test_create_telegram_client_uses_string_session():
    tg = main.create_telegram_client(
        {"api_id": 1, "api_hash": "h", "session_string": ""}
    )
    assert isinstance(tg.session, main.StringSession)
    assert tg.flood_sleep_threshold == main.FLOOD_SLEEP_THRESHOLD


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
async def test_get_me():
    client = fake_client()
    client.get_me.return_value = user(phone="15550001", premium=True)
    _, data = await call("get_me", {}, client)
    assert data == {
        "id": 42,
        "type": "user",
        "name": "Ada Lovelace",
        "username": "ada",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "phone": "15550001",
        "premium": True,
    }


async def test_list_chats_filters_and_formats():
    client = fake_client()
    group = mock.Mock(
        entity=supergroup(),
        unread_count=3,
        pinned=True,
        archived=False,
        message=message(5, "q3 numbers", types.PeerChannel(777), types.PeerUser(42)),
    )
    direct = mock.Mock(
        entity=user(), unread_count=0, pinned=False, archived=False, message=None
    )
    client.get_dialogs.return_value = [group, direct]

    _, data = await call("list_chats", {"unread_only": True, "limit": 5}, client)

    client.get_dialogs.assert_awaited_once_with(limit=main.MAX_DIALOGS, archived=False)
    assert data["count"] == 1
    chat = data["chats"][0]
    assert chat["id"] == -1000000000777
    assert chat["type"] == "supergroup"
    assert chat["unread_count"] == 3
    assert chat["pinned"] is True
    assert chat["last_message"]["text"] == "q3 numbers"
    assert chat["last_message"]["sender_id"] == 42


async def test_get_messages_paginates_and_warms_cache_for_numeric_ids():
    client = fake_client()
    entity = supergroup()
    client.get_entity.side_effect = [ValueError("not cached"), entity]
    client.get_messages.return_value = [
        message(9, "b", types.PeerChannel(777), types.PeerUser(1)),
        message(8, "a", types.PeerChannel(777), types.PeerUser(2)),
    ]

    _, data = await call(
        "get_messages", {"chat_id": "-1000000000777", "limit": 2}, client
    )

    assert client.get_entity.await_args_list[0].args == (-1000000000777,)
    client.get_dialogs.assert_awaited_once_with(limit=main.DIALOG_WARMUP_LIMIT)
    client.get_messages.assert_awaited_once_with(entity, limit=2)
    assert [m["id"] for m in data["messages"]] == [9, 8]
    assert data["next_offset_id"] == 8


async def test_unknown_numeric_chat_has_clear_error():
    client = fake_client()
    client.get_entity.side_effect = ValueError("not cached")
    result, text = await call("get_chat", {"chat_id": "123"}, client)
    assert result.is_error
    assert "list_chats" in text


async def test_get_chat_includes_full_details():
    client = fake_client()
    entity = supergroup()
    client.get_entity.return_value = entity
    full = mock.Mock()
    full.full_chat.about = "Month-end close"
    full.full_chat.participants_count = 12

    async def tl_call(request):
        assert type(request).__name__ == "GetFullChannelRequest"
        return full

    client.side_effect = tl_call
    _, data = await call("get_chat", {"chat_id": "@finance_team"}, client)
    client.get_entity.assert_awaited_once_with("@finance_team")
    assert data["about"] == "Month-end close"
    assert data["participants_count"] == 12


async def test_send_message_with_reply_and_html():
    client = fake_client()
    client.get_entity.return_value = user()
    client.send_message.return_value = message(11, "<b>hi</b>", out=True)

    _, data = await call(
        "send_message",
        {
            "chat_id": "@ada",
            "text": "<b>hi</b>",
            "parse_mode": "html",
            "reply_to_message_id": 10,
            "silent": True,
        },
        client,
    )

    client.send_message.assert_awaited_once_with(
        client.get_entity.return_value,
        "<b>hi</b>",
        parse_mode="html",
        reply_to=10,
        silent=True,
    )
    assert data["sent"] is True
    assert data["message"]["id"] == 11
    assert data["message"]["out"] is True


async def test_send_message_requires_text():
    client = fake_client()
    client.get_entity.return_value = user()
    result, text = await call("send_message", {"chat_id": "me", "text": " "}, client)
    assert result.is_error
    assert "text is required" in text
    client.send_message.assert_not_awaited()


async def test_search_messages_globally():
    client = fake_client()
    client.get_messages.return_value = [message(3, "invoice 42")]
    _, data = await call("search_messages", {"query": "invoice"}, client)
    client.get_messages.assert_awaited_once_with(None, search="invoice", limit=20)
    assert data["messages"][0]["text"] == "invoice 42"


async def test_search_messages_from_user_requires_chat():
    client = fake_client()
    result, text = await call(
        "search_messages", {"query": "x", "from_user": "@ada"}, client
    )
    assert result.is_error
    assert "requires chat_id" in text


async def test_edit_message():
    client = fake_client()
    client.get_entity.return_value = user()
    client.edit_message.return_value = message(11, "fixed", out=True)
    _, data = await call(
        "edit_message",
        {"chat_id": "me", "message_id": 11, "text": "fixed", "parse_mode": "none"},
        client,
    )
    client.get_entity.assert_awaited_once_with("me")
    client.edit_message.assert_awaited_once_with(
        client.get_entity.return_value, 11, "fixed", parse_mode=None
    )
    assert data["edited"] is True


async def test_delete_messages():
    client = fake_client()
    client.get_entity.return_value = user()
    client.delete_messages.return_value = [
        types.messages.AffectedMessages(pts=1, pts_count=2)
    ]
    _, data = await call(
        "delete_messages", {"chat_id": "@ada", "message_ids": [1, 2]}, client
    )
    client.delete_messages.assert_awaited_once_with(
        client.get_entity.return_value, [1, 2], revoke=True
    )
    assert data == {"deleted_count": 2, "message_ids": [1, 2], "revoke": True}


async def test_delete_messages_rejects_empty_ids():
    client = fake_client()
    client.get_entity.return_value = user()
    result, text = await call(
        "delete_messages", {"chat_id": "@ada", "message_ids": []}, client
    )
    assert result.is_error
    client.delete_messages.assert_not_awaited()


async def test_forward_messages():
    client = fake_client()
    source, target = supergroup(), user()
    client.get_entity.side_effect = [source, target]
    client.forward_messages.return_value = [message(20, "fwd", out=True)]
    _, data = await call(
        "forward_messages",
        {"from_chat_id": "@finance_team", "to_chat_id": "@ada", "message_ids": [5]},
        client,
    )
    client.forward_messages.assert_awaited_once_with(target, [5], source)
    assert data["forwarded_count"] == 1


async def test_mark_as_read():
    client = fake_client()
    client.get_entity.return_value = user()
    client.send_read_acknowledge.return_value = True
    _, data = await call("mark_as_read", {"chat_id": "42", "max_message_id": 9}, client)
    client.send_read_acknowledge.assert_awaited_once_with(
        client.get_entity.return_value, max_id=9
    )
    assert data == {"marked_as_read": True, "chat_id": 42}


async def test_list_contacts():
    client = fake_client()
    contacts = types.contacts.Contacts(
        contacts=[], saved_count=0, users=[user(1, contact=True), user(2)]
    )

    async def tl_call(request):
        assert type(request).__name__ == "GetContactsRequest"
        return contacts

    client.side_effect = tl_call
    _, data = await call("list_contacts", {"limit": 1}, client)
    assert data["count"] == 1
    assert data["total"] == 2
    assert data["contacts"][0]["contact"] is True


async def test_resolve_username_accepts_links():
    client = fake_client()
    client.get_entity.return_value = user()
    _, data = await call(
        "resolve_username", {"username": "https://t.me/ada_lovelace"}, client
    )
    client.get_entity.assert_awaited_once_with("ada_lovelace")
    assert data["username"] == "ada"


async def test_resolve_username_rejects_invalid_value():
    client = fake_client()
    result, _ = await call("resolve_username", {"username": "@a b"}, client)
    assert result.is_error
    client.get_entity.assert_not_awaited()


async def test_get_user_by_phone():
    client = fake_client()
    client.get_entity.return_value = user()
    full = mock.Mock()
    full.full_user.about = "Analyst"
    client.side_effect = mock.AsyncMock(return_value=full)
    _, data = await call("get_user", {"user": "+15550001"}, client)
    client.get_entity.assert_awaited_once_with("+15550001")
    assert data["about"] == "Analyst"


async def test_get_participants_admins():
    client = fake_client()
    client.get_entity.return_value = supergroup()
    client.get_participants.return_value = [user(1), user(2, bot=True)]
    _, data = await call(
        "get_participants",
        {"chat_id": "@finance_team", "filter": "admins", "limit": 10},
        client,
    )
    kwargs = client.get_participants.await_args.kwargs
    assert kwargs["limit"] == 10
    assert isinstance(kwargs["filter"], types.ChannelParticipantsAdmins)
    assert [p["type"] for p in data["participants"]] == ["user", "bot"]


async def test_unknown_tool():
    client = fake_client()
    result, text = await call("nope", {}, client)
    assert result.is_error
    client.connect.assert_not_awaited()


def test_parse_peer():
    assert main.parse_peer("-100123") == -100123
    assert main.parse_peer(5) == 5
    assert main.parse_peer("@ada") == "@ada"
    assert main.parse_peer("Self") == "me"
    with pytest.raises(ValueError):
        main.parse_peer("")
    with pytest.raises(ValueError):
        main.parse_peer(None)
