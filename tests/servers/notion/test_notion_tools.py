"""Offline tests for the Notion MCP server tools, with a mocked Notion client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from src.servers.notion import main

PAGE_ID = "34eef81e112742eab82ba4a3530600c7"
DB_ID = "c0343e8e89fa4c0f82466b5c34f3c08a"


def _mock_client():
    client = MagicMock()
    client.databases.query = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )
    client.pages.create = AsyncMock(return_value={"id": PAGE_ID})
    client.pages.update = AsyncMock(return_value={"id": PAGE_ID})
    return client


async def _invoke(name, arguments, client):
    server = main.create_server("test-user", api_key="test-key")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    with patch.object(
        main, "create_notion_client", new_callable=AsyncMock, return_value=client
    ):
        return await server.dispatch(request)


@pytest.mark.asyncio
async def test_query_database_minimal_call():
    client = _mock_client()
    result = await _invoke("query_database", {"database_id": DB_ID}, client)

    assert result.is_error is False
    client.databases.query.assert_awaited_once_with(database_id=DB_ID)


@pytest.mark.asyncio
async def test_query_database_forwards_filter_sorts_and_pagination():
    client = _mock_client()
    args = {
        "database_id": DB_ID,
        "filter": {"property": "Status", "status": {"equals": "Open"}},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 50,
        "start_cursor": "cursor-1",
    }
    result = await _invoke("query_database", args, client)

    assert result.is_error is False
    client.databases.query.assert_awaited_once_with(**args)


@pytest.mark.asyncio
async def test_create_page_forwards_children():
    client = _mock_client()
    props = {"Name": {"title": [{"text": {"content": "Save returns 500"}}]}}
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": "x"}}]},
        }
    ]
    result = await _invoke(
        "create_page",
        {"database_id": DB_ID, "properties": props, "children": children},
        client,
    )

    assert result.is_error is False
    client.pages.create.assert_awaited_once_with(
        parent={"database_id": DB_ID}, properties=props, children=children
    )


@pytest.mark.asyncio
async def test_create_page_without_children():
    client = _mock_client()
    props = {"Name": {"title": [{"text": {"content": "Ticket"}}]}}
    result = await _invoke(
        "create_page", {"database_id": DB_ID, "properties": props}, client
    )

    assert result.is_error is False
    client.pages.create.assert_awaited_once_with(
        parent={"database_id": DB_ID}, properties=props
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [PAGE_ID, f"https://www.notion.so/workspace/Bug-ticket-{PAGE_ID}"],
)
async def test_update_page_forwards_properties(page):
    client = _mock_client()
    props = {"Status": {"status": {"name": "Resolved"}}}
    result = await _invoke("update_page", {"page": page, "properties": props}, client)

    assert result.is_error is False
    assert json.loads(result.content[0].text)["id"] == PAGE_ID
    client.pages.update.assert_awaited_once_with(page_id=PAGE_ID, properties=props)


@pytest.mark.asyncio
async def test_notion_api_error_is_returned_as_tool_error():
    client = _mock_client()
    client.pages.update.side_effect = RuntimeError("Notion 404 object_not_found")
    result = await _invoke("update_page", {"page": PAGE_ID, "properties": {}}, client)

    assert result.is_error is True
    assert "Notion 404 object_not_found" in result.content[0].text
