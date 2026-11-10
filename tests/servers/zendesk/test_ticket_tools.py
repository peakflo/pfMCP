"""Offline coverage for Zendesk ticket extensions and Nango routing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListResourcesRequest,
    ListToolsRequest,
)

from src.servers.zendesk import main
from src.utils.zendesk import util


async def invoke(name, arguments, response):
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    with (
        patch.object(
            main, "get_credentials", new_callable=AsyncMock, return_value="token"
        ),
        patch.object(
            main,
            "get_service_config",
            new_callable=AsyncMock,
            return_value={"custom_subdomain": "example"},
        ),
        patch.object(main, "make_zendesk_request", new_callable=AsyncMock) as api,
    ):
        api.return_value = response
        result = await server.dispatch(request)
    return result, api


@pytest.mark.asyncio
async def test_existing_and_new_tools_are_listed():
    result = await main.create_server("connection-1").dispatch(
        ListToolsRequest(method="tools/list")
    )
    assert {tool.name for tool in result.tools} == {
        "list_tickets",
        "get_ticket",
        "search_tickets",
        "create_ticket",
        "update_ticket",
        "add_comment",
    }


@pytest.mark.asyncio
async def test_list_tickets_returns_cursor():
    result, api = await invoke(
        "list_tickets",
        {"page_size": 2, "after_cursor": "cursor-1"},
        {
            "tickets": [{"id": 42}],
            "meta": {"has_more": True, "after_cursor": "cursor-2"},
        },
    )
    assert json.loads(result.content[0].text) == {
        "tickets": [{"id": 42}],
        "has_more": True,
        "next_cursor": "cursor-2",
    }
    api.assert_awaited_once_with(
        "get",
        "tickets.json",
        "token",
        "example",
        data=None,
        params={"page[size]": 2, "page[after]": "cursor-1"},
        connection_id=None,
    )


@pytest.mark.asyncio
async def test_existing_view_resources_are_preserved():
    server = main.create_server("connection-1")
    with (
        patch.object(
            main, "get_credentials", new_callable=AsyncMock, return_value="token"
        ),
        patch.object(
            main,
            "get_service_config",
            new_callable=AsyncMock,
            return_value={"custom_subdomain": "example"},
        ),
        patch.object(
            main,
            "make_zendesk_request",
            new_callable=AsyncMock,
            return_value={"views": [{"id": 7, "title": "Open tickets"}]},
        ),
    ):
        result = await server.dispatch(ListResourcesRequest(method="resources/list"))
    assert str(result.resources[0].uri) == "zendesk://view/7"


@pytest.mark.asyncio
async def test_get_ticket():
    result, api = await invoke("get_ticket", {"ticket_id": 42}, {"ticket": {"id": 42}})
    assert json.loads(result.content[0].text) == {"id": 42}
    api.assert_awaited_once_with(
        "get",
        "tickets/42.json",
        "token",
        "example",
        data=None,
        params=None,
        connection_id=None,
    )


@pytest.mark.asyncio
async def test_search_is_ticket_scoped_and_legacy_result_remains_readable():
    result, api = await invoke(
        "search_tickets",
        {"query": "status:open", "page": 2},
        {
            "results": [{"id": 42, "subject": "Help", "result_type": "ticket"}],
            "next_page": "https://example.test/page=3",
        },
    )
    assert "Ticket #42" in result.content[0].text
    assert "Next page: https://example.test/page=3" in result.content[0].text
    assert api.await_args.kwargs["params"]["query"] == "type:ticket status:open"
    assert api.await_args.kwargs["params"]["page"] == 2


@pytest.mark.asyncio
async def test_existing_create_and_comment_still_work():
    created, create_api = await invoke(
        "create_ticket",
        {"subject": "Help", "comment": "Please help"},
        {"ticket": {"id": 42, "subject": "Help", "status": "new"}},
    )
    assert "Ticket created successfully" in created.content[0].text
    assert create_api.await_args.kwargs["data"]["ticket"]["comment"] == {
        "body": "Please help"
    }
    commented, comment_api = await invoke(
        "add_comment",
        {"ticket_id": 42, "comment": "Private", "public": False},
        {"ticket": {"id": 42, "subject": "Help"}},
    )
    assert "internal note" in commented.content[0].text
    assert comment_api.await_args.kwargs["data"]["ticket"]["comment"]["public"] is False


@pytest.mark.asyncio
async def test_local_auth_uses_existing_helpers():
    result, api = await invoke(
        "update_ticket",
        {"ticket_id": 42, "status": "pending"},
        {"ticket": {"id": 42, "status": "pending"}},
    )
    assert "Ticket updated successfully" in result.content[0].text
    assert api.await_args.kwargs["data"] == {"ticket": {"status": "pending"}}


@pytest.mark.asyncio
async def test_nango_mode_resolves_credentials_without_local_subdomain(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "nango")
    auth = MagicMock(spec=["get_user_credentials"])
    auth.get_user_credentials.return_value = {"access_token": "oauth-token"}
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="get_ticket", arguments={"ticket_id": 42}),
    )
    with (
        patch.object(main, "create_auth_client", return_value=auth),
        patch.object(
            main,
            "make_zendesk_request",
            new_callable=AsyncMock,
            return_value={"ticket": {"id": 42}},
        ) as api,
    ):
        result = await server.dispatch(request)
    assert json.loads(result.content[0].text) == {"id": 42}
    auth.get_user_credentials.assert_called_once_with("zendesk", "connection-1")
    assert api.await_args.kwargs["connection_id"] == "connection-1"


@pytest.mark.asyncio
async def test_nango_proxy_uses_mapped_provider_key(monkeypatch):
    monkeypatch.setenv("NANGO_SECRET_KEY", "secret")
    monkeypatch.setenv("NANGO_HOST", "https://nango.test")
    response = httpx.Response(
        200,
        json={"tickets": []},
        request=httpx.Request("GET", "https://nango.test/proxy/api/v2/tickets.json"),
    )
    client = AsyncMock()
    client.get.return_value = response
    client.__aenter__.return_value = client
    with (
        patch.object(main.httpx, "AsyncClient", return_value=client),
        patch.dict(
            main.SERVICE_NAME_MAP, {"zendesk": {"nango_service_name": "test-provider"}}
        ),
    ):
        result = await main.make_zendesk_request(
            "get", "tickets.json", "oauth-token", connection_id="connection-1"
        )
    assert result == {"tickets": []}
    assert (
        client.get.await_args.kwargs["headers"]["Provider-Config-Key"]
        == "test-provider"
    )
    assert client.get.await_args.kwargs["headers"]["Connection-Id"] == "connection-1"


def test_nango_ticket_link_uses_agent_url():
    ticket = {
        "id": 42,
        "url": "https://example.zendesk.com/api/v2/tickets/42.json",
    }
    assert (
        main.ticket_url(ticket, None) == "https://example.zendesk.com/agent/tickets/42"
    )
    assert main.ticket_url({**ticket, "url": "https://other.test/ticket"}, None) == ""


@pytest.mark.asyncio
async def test_search_rejects_bad_page_size():
    result, api = await invoke(
        "search_tickets", {"query": "status:open", "per_page": 101}, {}
    )
    assert result.is_error is True
    assert "per_page" in result.content[0].text
    api.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_api_failure_is_tool_error():
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="add_comment", arguments={"ticket_id": 42, "comment": "Reply"}
        ),
    )
    with (
        patch.object(
            main, "get_credentials", new_callable=AsyncMock, return_value="token"
        ),
        patch.object(
            main,
            "get_service_config",
            new_callable=AsyncMock,
            return_value={"custom_subdomain": "example"},
        ),
        patch.object(
            main,
            "make_zendesk_request",
            new_callable=AsyncMock,
            side_effect=ValueError("Zendesk API error: 403"),
        ),
    ):
        result = await server.dispatch(request)
    assert result.is_error is True
    assert "403" in result.content[0].text


def test_local_refresh_uses_zendesk_refresh_grant():
    assert util.build_zendesk_refresh_token_data(
        {"client_id": "client", "client_secret": "secret"},
        "refresh-token",
        {},
    ) == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "client_id": "client",
        "client_secret": "secret",
    }


@pytest.mark.asyncio
async def test_local_refresh_failure_does_not_return_expired_token(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    auth = MagicMock()
    auth.get_user_credentials.return_value = {"access_token": "expired-token"}
    auth.get_oauth_config.return_value = {
        "custom_subdomain": "example",
        "client_id": "client",
        "client_secret": "secret",
    }
    with (
        patch("src.auth.factory.create_auth_client", return_value=auth),
        patch.object(
            util,
            "refresh_token_if_needed",
            new_callable=AsyncMock,
            side_effect=ValueError("refresh failed"),
        ),
    ):
        with pytest.raises(ValueError, match="refresh failed"):
            await util.get_credentials("connection-1", "zendesk")
