"""Focused BigQuery transport and result handling tests; no live credentials needed."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from mcp.types import CallToolRequest, CallToolRequestParams

from src.auth.constants import SERVICE_NAME_MAP
from src.servers.bigquery.main import _execute, create_server


def test_query_uses_billing_limit_and_formats_rows():
    response = Mock()
    response.json.return_value = {
        "jobComplete": True,
        "schema": {"fields": [{"name": "total"}]},
        "rows": [{"f": [{"v": "42"}]}],
    }
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=response
    ) as request:
        result = _execute(
            "secret",
            "run_query",
            {"project_id": "my-project", "sql": "SELECT 42 AS total"},
        )
    assert result["rows"] == [{"total": "42"}]
    args, kwargs = request.call_args
    assert args == (
        "POST",
        "https://bigquery.googleapis.com/bigquery/v2/projects/my-project/queries",
    )
    assert kwargs["json"]["maximumBytesBilled"] == "1000000000"
    assert kwargs["json"]["useLegacySql"] is False
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_query_result_page_preserves_token_and_location():
    response = Mock()
    response.json.return_value = {"jobComplete": False, "rows": [], "pageToken": "next"}
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=response
    ) as request:
        result = _execute(
            "secret",
            "get_query_results",
            {
                "project_id": "p",
                "job_id": "job/1",
                "location": "asia-southeast1",
                "page_token": "prior",
            },
        )
    assert result["pageToken"] == "next"
    assert request.call_args.args[1].endswith("/projects/p/queries/job%2F1")
    assert request.call_args.kwargs["params"]["location"] == "asia-southeast1"


@pytest.mark.asyncio
async def test_server_exposes_all_bigquery_tools():
    server = create_server("test-user")
    tools = await server._pf_list_tools()
    assert {tool.name for tool in tools} == {
        "list_datasets",
        "list_tables",
        "get_table",
        "run_query",
        "get_query_results",
    }


@pytest.mark.asyncio
async def test_server_uses_bigquery_nango_connection():
    assert SERVICE_NAME_MAP["bigquery"]["nango_service_name"] == "google"
    auth = Mock()
    auth.get_user_credentials.return_value = {"access_token": "oauth-token"}
    response = Mock()
    response.json.return_value = {"datasets": []}
    with patch(
        "src.servers.bigquery.main.create_auth_client", return_value=auth
    ), patch(
        "src.servers.bigquery.main.requests.request", return_value=response
    ) as request:
        result = await create_server("connection-id").dispatch(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="list_datasets", arguments={"project_id": "project-id"}
                )
            )
        )
    auth.get_user_credentials.assert_called_once_with("bigquery", "connection-id")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer oauth-token"
    assert result.is_error is False
    assert json.loads(result.content[0].text) == {"datasets": []}


@pytest.mark.asyncio
async def test_missing_oauth_token_is_mcp_error():
    auth = Mock()
    auth.get_user_credentials.return_value = {}
    with patch(
        "src.servers.bigquery.main.create_auth_client", return_value=auth
    ), patch("src.servers.bigquery.main.requests.request") as request:
        result = await create_server("connection-id").dispatch(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="list_datasets", arguments={"project_id": "project-id"}
                )
            )
        )
    assert result.is_error is True
    assert "no access token" in result.content[0].text
    request.assert_not_called()


@pytest.mark.asyncio
async def test_bigquery_http_failure_is_mcp_error():
    auth = Mock()
    auth.get_user_credentials.return_value = {"access_token": "oauth-token"}
    response = Mock(status_code=403, reason="Forbidden")
    response.raise_for_status.side_effect = requests.HTTPError("403")
    response.json.return_value = {"error": {"message": "Permission denied"}}
    with patch(
        "src.servers.bigquery.main.create_auth_client", return_value=auth
    ), patch("src.servers.bigquery.main.requests.request", return_value=response):
        result = await create_server("connection-id").dispatch(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="list_datasets", arguments={"project_id": "project-id"}
                )
            )
        )
    assert result.is_error is True
    assert "BigQuery API error (403): Permission denied" in result.content[0].text
