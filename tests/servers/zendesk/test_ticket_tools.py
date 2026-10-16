"""Focused Zendesk ticket tool tests without a live connection."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from src.servers.zendesk import main


async def invoke(name, arguments, response):
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    with patch.object(main, "make_zendesk_request", new_callable=AsyncMock) as api:
        api.return_value = response
        result = await server.dispatch(request)
    return json.loads(result.content[0].text), api


@pytest.mark.asyncio
async def test_tools_match_config():
    server = main.create_server("connection-1")
    result = await server.dispatch(ListToolsRequest(method="tools/list"))
    assert {tool.name for tool in result.tools} == {
        "list_tickets",
        "get_ticket",
        "search_tickets",
        "update_ticket",
    }


@pytest.mark.asyncio
async def test_list_tickets_returns_cursor_and_scopes_connection():
    output, api = await invoke(
        "list_tickets",
        {"page_size": 2, "after_cursor": "cursor-1"},
        {
            "tickets": [{"id": 42}],
            "meta": {"has_more": True, "after_cursor": "cursor-2"},
        },
    )
    assert output == {
        "tickets": [{"id": 42}],
        "next_cursor": "cursor-2",
        "has_more": True,
    }
    api.assert_awaited_once_with(
        "GET",
        "tickets.json",
        "connection-1",
        None,
        params={"page[size]": 2, "page[after]": "cursor-1"},
    )


@pytest.mark.asyncio
async def test_read_ticket():
    output, api = await invoke("get_ticket", {"ticket_id": 42}, {"ticket": {"id": 42}})
    assert output == {"id": 42}
    api.assert_awaited_once_with("GET", "tickets/42.json", "connection-1", None)


@pytest.mark.asyncio
async def test_search_is_ticket_scoped_and_paginated():
    output, api = await invoke(
        "search_tickets",
        {"query": "status:open", "page": 2, "page_size": 10},
        {
            "results": [{"id": 42, "result_type": "ticket"}],
            "count": 12,
            "next_page": "https://example.test/page=3",
        },
    )
    assert output["count"] == 12
    assert output["next_page"] == "https://example.test/page=3"
    assert api.await_args.kwargs["params"] == {
        "query": "type:ticket status:open",
        "page": 2,
        "per_page": 10,
    }


@pytest.mark.asyncio
async def test_update_ticket_internal_note():
    output, api = await invoke(
        "update_ticket",
        {"ticket_id": 42, "status": "pending", "comment": "Checking", "public": False},
        {"ticket": {"id": 42, "status": "pending"}},
    )
    assert output["status"] == "pending"
    api.assert_awaited_once_with(
        "PUT",
        "tickets/42.json",
        "connection-1",
        None,
        data={
            "ticket": {
                "status": "pending",
                "comment": {"body": "Checking", "public": False},
            }
        },
    )


@pytest.mark.asyncio
async def test_rejects_invalid_update_before_request():
    server = main.create_server("connection-1")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="update_ticket", arguments={"ticket_id": 42}),
    )
    with patch.object(main, "make_zendesk_request", new_callable=AsyncMock) as api:
        result = await server.dispatch(request)
        assert result.is_error
        assert "At least one" in result.content[0].text
        api.assert_not_awaited()


@pytest.mark.asyncio
async def test_nango_proxy_uses_connection_and_no_token_in_headers(monkeypatch):
    monkeypatch.setenv("NANGO_SECRET_KEY", "secret")
    monkeypatch.setenv("NANGO_HOST", "https://nango.test")
    auth = MagicMock()
    auth.async_get_user_credentials = AsyncMock(
        return_value={"access_token": "oauth-token"}
    )
    response = httpx.Response(
        200,
        json={"tickets": []},
        request=httpx.Request("GET", "https://nango.test/proxy/api/v2/tickets.json"),
    )
    client = AsyncMock()
    client.request.return_value = response
    client.__aenter__.return_value = client
    with patch.object(main, "create_auth_client", return_value=auth), patch.object(
        main.httpx, "AsyncClient", return_value=client
    ):
        result = await main.make_zendesk_request("GET", "tickets.json", "connection-1")
    assert result == {"tickets": []}
    auth.async_get_user_credentials.assert_awaited_once_with("zendesk", "connection-1")
    assert client.request.await_args.kwargs["headers"] == {
        "Authorization": "Bearer secret",
        "Provider-Config-Key": "zendesk",
        "Connection-Id": "connection-1",
    }
