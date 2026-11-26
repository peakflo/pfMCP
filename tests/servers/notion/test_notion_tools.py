"""Offline unit tests for Notion MCP server tools.

Mocks the Notion AsyncClient to verify update_page, query_database filtering/
sorting/pagination/bounds, create_page with and without children, URL/ID
resolution, and invalid-input validation without requiring live credentials.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from src.servers.notion import main


def _build_mock_notion_client():
    """Create a mock Notion AsyncClient with async endpoint methods."""
    client = MagicMock()
    client.users = MagicMock()
    client.users.list = AsyncMock(return_value={"object": "list", "results": []})
    client.search = AsyncMock(return_value={"object": "list", "results": []})
    client.databases = MagicMock()
    client.databases.query = AsyncMock(
        return_value={
            "object": "list",
            "results": [{"id": "page-1"}],
            "has_more": False,
            "next_cursor": None,
        }
    )
    client.pages = MagicMock()
    client.pages.retrieve = AsyncMock(return_value={"id": "page-1", "object": "page"})
    client.pages.create = AsyncMock(return_value={"id": "new-page-1", "object": "page"})
    client.pages.update = AsyncMock(
        return_value={"id": "page-1", "object": "page", "archived": False}
    )
    client.blocks = MagicMock()
    client.blocks.children = MagicMock()
    client.blocks.children.append = AsyncMock(return_value={"results": []})
    client.blocks.children.list = AsyncMock(return_value={"results": []})
    client.comments = MagicMock()
    client.comments.create = AsyncMock(return_value={"id": "comment-1"})
    return client


async def _invoke(name: str, arguments: dict, mock_client=None):
    """Dispatch a Notion MCP tool call through Server.dispatch with mocked client."""
    if mock_client is None:
        mock_client = _build_mock_notion_client()

    server = main.create_server("test-user", api_key="test-key")
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )

    with patch.object(
        main,
        "create_notion_client",
        new_callable=AsyncMock,
        return_value=mock_client,
    ) as create_client_mock:
        result = await server.dispatch(request)

    return result, mock_client, create_client_mock


@pytest.mark.asyncio
async def test_list_tools_includes_update_page_and_updated_schemas():
    server = main.create_server("test-user")
    result = await server.dispatch(ListToolsRequest(method="tools/list"))
    tools_by_name = {tool.name: tool for tool in result.tools}

    assert {
        "list_all_users",
        "search_pages",
        "list_databases",
        "query_database",
        "get_page",
        "create_page",
        "update_page",
        "append_blocks",
        "get_block_children",
        "comment_on_page",
        "comment_on_block",
    }.issubset(tools_by_name.keys())

    update_schema = tools_by_name["update_page"].input_schema
    assert update_schema["required"] == ["page"]
    assert set(update_schema["properties"].keys()) == {
        "page",
        "properties",
        "archived",
        "icon",
        "cover",
    }

    query_schema = tools_by_name["query_database"].input_schema
    assert query_schema["required"] == ["database_id"]
    assert {"database_id", "filter", "sorts", "page_size", "start_cursor"} == set(
        query_schema["properties"].keys()
    )
    assert query_schema["properties"]["page_size"]["minimum"] == 1
    assert query_schema["properties"]["page_size"]["maximum"] == 100

    create_schema = tools_by_name["create_page"].input_schema
    assert create_schema["required"] == ["database_id", "properties"]
    assert {"database_id", "properties", "children"} == set(
        create_schema["properties"].keys()
    )


# ----------------------------------------------------------------- update_page
@pytest.mark.asyncio
async def test_update_page_with_page_id_and_properties():
    mock_client = _build_mock_notion_client()
    mock_client.pages.update.return_value = {
        "id": "34eef81e-1127-42ea-b82b-a4a3530600c7",
        "object": "page",
        "properties": {"Status": {"status": {"name": "Resolved"}}},
    }

    props = {"Status": {"status": {"name": "Resolved"}}}
    result, _, _ = await _invoke(
        "update_page",
        {"page": "34eef81e-1127-42ea-b82b-a4a3530600c7", "properties": props},
        mock_client,
    )

    assert result.is_error is False
    assert json.loads(result.content[0].text)["id"] == (
        "34eef81e-1127-42ea-b82b-a4a3530600c7"
    )
    mock_client.pages.update.assert_awaited_once_with(
        page_id="34eef81e-1127-42ea-b82b-a4a3530600c7",
        properties=props,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.notion.so/peakflo/QA-Bug-Ticket-34eef81e112742eab82ba4a3530600c7",
        "https://peakflo.notion.site/QA-Bug-34eef81e112742eab82ba4a3530600c7?pvs=4",
    ],
)
async def test_update_page_extracts_id_from_notion_url(url):
    mock_client = _build_mock_notion_client()
    result, _, _ = await _invoke(
        "update_page",
        {"page": url, "archived": True},
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.update.assert_awaited_once_with(
        page_id="34eef81e112742eab82ba4a3530600c7",
        archived=True,
    )


@pytest.mark.asyncio
async def test_update_page_supports_archived_false_alone():
    """archived=False is falsy and must still count as a valid update field."""
    mock_client = _build_mock_notion_client()
    result, _, _ = await _invoke(
        "update_page",
        {"page": "page-123", "archived": False},
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.update.assert_awaited_once_with(
        page_id="page-123",
        archived=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("icon", {"type": "emoji", "emoji": "🐛"}),
        (
            "cover",
            {"type": "external", "external": {"url": "https://example.com/c.png"}},
        ),
    ],
)
async def test_update_page_supports_icon_or_cover_alone(field, value):
    mock_client = _build_mock_notion_client()
    result, _, _ = await _invoke(
        "update_page",
        {"page": "page-123", field: value},
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.update.assert_awaited_once_with(
        page_id="page-123",
        **{field: value},
    )


@pytest.mark.asyncio
async def test_update_page_supports_icon_cover_and_all_fields():
    mock_client = _build_mock_notion_client()
    props = {"Severity": {"select": {"name": "P1"}}}
    icon = {"type": "emoji", "emoji": "🐛"}
    cover = {"type": "external", "external": {"url": "https://example.com/banner.png"}}

    result, _, _ = await _invoke(
        "update_page",
        {
            "page": "page-123",
            "properties": props,
            "archived": False,
            "icon": icon,
            "cover": cover,
        },
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.update.assert_awaited_once_with(
        page_id="page-123",
        properties=props,
        archived=False,
        icon=icon,
        cover=cover,
    )


@pytest.mark.asyncio
async def test_update_page_rejects_missing_update_fields():
    result, mock_client, create_client = await _invoke(
        "update_page",
        {"page": "page-123"},
    )

    assert result.is_error is True
    assert "At least one of" in result.content[0].text
    create_client.assert_not_awaited()
    mock_client.pages.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"page": ""},
        {"page": "   "},
        {"page": "https://www.notion.so/peakflo/no-valid-id-here", "archived": True},
        {"page": "page-123", "properties": {}},
        {"page": "page-123", "icon": {}},
        {"page": "page-123", "cover": {}},
        {"page": "page-123", "archived": "yes"},
        {"page": "page-123", "properties": ["bad"]},
    ],
)
async def test_update_page_rejects_invalid_inputs(arguments):
    result, mock_client, create_client = await _invoke("update_page", arguments)

    assert result.is_error is True
    create_client.assert_not_awaited()
    mock_client.pages.update.assert_not_awaited()


# -------------------------------------------------------------- query_database
@pytest.mark.asyncio
async def test_query_database_backward_compatible_minimal_call():
    mock_client = _build_mock_notion_client()
    mock_client.databases.query.return_value = {
        "object": "list",
        "results": [{"id": "bug-1"}, {"id": "bug-2"}],
        "has_more": False,
        "next_cursor": None,
    }

    result, _, _ = await _invoke(
        "query_database",
        {"database_id": "db-123"},
        mock_client,
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["object"] == "list"
    assert payload["results"] == [{"id": "bug-1"}, {"id": "bug-2"}]
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None
    mock_client.databases.query.assert_awaited_once_with(database_id="db-123")


@pytest.mark.asyncio
async def test_query_database_normalizes_missing_pagination_fields():
    mock_client = _build_mock_notion_client()
    mock_client.databases.query.return_value = {"results": [{"id": "bug-1"}]}

    result, _, _ = await _invoke(
        "query_database",
        {"database_id": "db-123"},
        mock_client,
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload == {
        "results": [{"id": "bug-1"}],
        "has_more": False,
        "next_cursor": None,
    }


@pytest.mark.asyncio
async def test_query_database_with_filter_sorts_page_size_and_cursor():
    mock_client = _build_mock_notion_client()
    mock_client.databases.query.return_value = {
        "object": "list",
        "results": [{"id": "bug-3"}],
        "has_more": True,
        "next_cursor": "cursor-page-2",
    }

    filter_obj = {
        "and": [
            {"property": "Status", "status": {"equals": "Open"}},
            {"property": "Severity", "select": {"equals": "P0"}},
        ]
    }
    sorts = [{"timestamp": "created_time", "direction": "descending"}]

    result, _, _ = await _invoke(
        "query_database",
        {
            "database_id": "db-123",
            "filter": filter_obj,
            "sorts": sorts,
            "page_size": 25,
            "start_cursor": "cursor-page-1",
        },
        mock_client,
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["results"] == [{"id": "bug-3"}]
    assert payload["has_more"] is True
    assert payload["next_cursor"] == "cursor-page-2"
    mock_client.databases.query.assert_awaited_once_with(
        database_id="db-123",
        filter=filter_obj,
        sorts=sorts,
        page_size=25,
        start_cursor="cursor-page-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [1, 100])
async def test_query_database_accepts_page_size_boundaries(page_size):
    mock_client = _build_mock_notion_client()
    result, _, _ = await _invoke(
        "query_database",
        {"database_id": "db-123", "page_size": page_size},
        mock_client,
    )

    assert result.is_error is False
    mock_client.databases.query.assert_awaited_once_with(
        database_id="db-123",
        page_size=page_size,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"database_id": ""},
        {"database_id": "   "},
        {"database_id": "db-123", "page_size": 0},
        {"database_id": "db-123", "page_size": -5},
        {"database_id": "db-123", "page_size": 101},
        {"database_id": "db-123", "page_size": True},
        {"database_id": "db-123", "page_size": "10"},
        {"database_id": "db-123", "filter": {}},
        {"database_id": "db-123", "filter": "invalid"},
        {"database_id": "db-123", "sorts": ["not-a-dict"]},
        {"database_id": "db-123", "sorts": [{}]},
        {"database_id": "db-123", "start_cursor": ""},
        {"database_id": "db-123", "start_cursor": "   "},
    ],
)
async def test_query_database_rejects_invalid_inputs(arguments):
    result, mock_client, create_client = await _invoke("query_database", arguments)

    assert result.is_error is True
    create_client.assert_not_awaited()
    mock_client.databases.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_database_omits_empty_sorts_list():
    mock_client = _build_mock_notion_client()
    result, _, _ = await _invoke(
        "query_database",
        {"database_id": "db-123", "sorts": []},
        mock_client,
    )

    assert result.is_error is False
    mock_client.databases.query.assert_awaited_once_with(database_id="db-123")


# ----------------------------------------------------------------- create_page
@pytest.mark.asyncio
async def test_create_page_without_children_preserves_existing_behavior():
    mock_client = _build_mock_notion_client()
    props = {"Name": {"title": [{"text": {"content": "Login button broken"}}]}}

    result, _, _ = await _invoke(
        "create_page",
        {"database_id": "db-qa", "properties": props},
        mock_client,
    )

    assert result.is_error is False
    assert json.loads(result.content[0].text)["id"] == "new-page-1"
    mock_client.pages.create.assert_awaited_once_with(
        parent={"database_id": "db-qa"},
        properties=props,
    )


@pytest.mark.asyncio
async def test_create_page_with_children_and_bookmark_blocks():
    mock_client = _build_mock_notion_client()
    props = {
        "Name": {"title": [{"text": {"content": "Invoice save returns 500"}}]},
        "Status": {"status": {"name": "Open"}},
    }
    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Repro Steps"}}]
            },
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "Click Save on AP Bill form."}}
                ]
            },
        },
        {
            "object": "block",
            "type": "bookmark",
            "bookmark": {
                "url": "https://spaces.peakflo.co/media/session-recording.mp4"
            },
        },
    ]

    result, _, _ = await _invoke(
        "create_page",
        {"database_id": "db-qa", "properties": props, "children": children},
        mock_client,
    )

    assert result.is_error is False
    assert json.loads(result.content[0].text)["id"] == "new-page-1"
    mock_client.pages.create.assert_awaited_once_with(
        parent={"database_id": "db-qa"},
        properties=props,
        children=children,
    )


@pytest.mark.asyncio
async def test_create_page_omits_empty_children_list():
    mock_client = _build_mock_notion_client()
    props = {"Name": {"title": [{"text": {"content": "Empty body ticket"}}]}}

    result, _, _ = await _invoke(
        "create_page",
        {"database_id": "db-qa", "properties": props, "children": []},
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.create.assert_awaited_once_with(
        parent={"database_id": "db-qa"},
        properties=props,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"database_id": "", "properties": {"Name": {}}},
        {"database_id": "db-qa", "properties": "not-an-object"},
        {"database_id": "db-qa", "properties": {}, "children": "not-a-list"},
        {"database_id": "db-qa", "properties": {}, "children": ["not-a-block"]},
        {"database_id": "db-qa", "properties": {}, "children": [{}]},
        {
            "database_id": "db-qa",
            "properties": {},
            "children": [{"object": "block", "type": "divider", "divider": {}}] * 101,
        },
    ],
)
async def test_create_page_rejects_invalid_inputs(arguments):
    result, mock_client, create_client = await _invoke("create_page", arguments)

    assert result.is_error is True
    create_client.assert_not_awaited()
    mock_client.pages.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_page_accepts_max_100_children_blocks():
    mock_client = _build_mock_notion_client()
    props = {"Name": {"title": [{"text": {"content": "Large ticket"}}]}}
    children = [{"object": "block", "type": "divider", "divider": {}}] * 100

    result, _, _ = await _invoke(
        "create_page",
        {"database_id": "db-qa", "properties": props, "children": children},
        mock_client,
    )

    assert result.is_error is False
    mock_client.pages.create.assert_awaited_once_with(
        parent={"database_id": "db-qa"},
        properties=props,
        children=children,
    )


@pytest.mark.asyncio
async def test_get_page_and_comment_on_page_resolve_id_and_url():
    mock_client = _build_mock_notion_client()
    url = "https://www.notion.so/peakflo/Ticket-34eef81e112742eab82ba4a3530600c7"

    get_result, _, _ = await _invoke("get_page", {"page": url}, mock_client)
    assert get_result.is_error is False
    mock_client.pages.retrieve.assert_awaited_once_with(
        page_id="34eef81e112742eab82ba4a3530600c7"
    )

    comment_result, _, _ = await _invoke(
        "comment_on_page",
        {"page": url, "comment": "Verified fixed in staging"},
        mock_client,
    )
    assert comment_result.is_error is False
    mock_client.comments.create.assert_awaited_once_with(
        parent={"page_id": "34eef81e112742eab82ba4a3530600c7"},
        rich_text=[{"type": "text", "text": {"content": "Verified fixed in staging"}}],
    )


# --------------------------------------------------------- error & helper paths
@pytest.mark.asyncio
async def test_notion_api_error_is_returned_as_tool_error():
    mock_client = _build_mock_notion_client()
    mock_client.pages.update.side_effect = RuntimeError("Notion 404 object_not_found")

    result, _, _ = await _invoke(
        "update_page",
        {"page": "page-missing", "archived": True},
        mock_client,
    )

    assert result.is_error is True
    assert "Notion 404 object_not_found" in result.content[0].text


def test_python_helpers_reject_bool_page_size_and_empty_update():
    """Direct helper checks verify validation even if schema validation is bypassed."""
    with pytest.raises(ValueError, match="page_size"):
        main._build_query_database_kwargs({"database_id": "db-1", "page_size": True})

    with pytest.raises(ValueError, match="At least one"):
        main._build_update_page_kwargs({"page": "page-1", "properties": None})

    with pytest.raises(ValueError, match="100"):
        main._build_create_page_kwargs(
            {
                "database_id": "db-1",
                "properties": {},
                "children": [{"type": "divider"}] * 101,
            }
        )
