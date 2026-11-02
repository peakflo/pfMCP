"""Focused BigQuery transport and result handling tests; no live credentials needed."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from mcp.types import CallToolRequest, CallToolRequestParams

from src.auth.constants import SERVICE_NAME_MAP
from src.servers.bigquery.main import _execute, create_server


def test_query_uses_billing_limit_and_formats_rows():
    dry_run = Mock()
    dry_run.json.return_value = {
        "configuration": {"dryRun": True, "query": {}},
        "statistics": {
            "query": {
                "statementType": "SELECT",
                "referencedTables": [
                    {"projectId": "my-project", "datasetId": "ds", "tableId": "t"}
                ],
            }
        },
    }
    response = Mock()
    response.json.return_value = {
        "jobComplete": True,
        "schema": {"fields": [{"name": "total"}]},
        "rows": [{"f": [{"v": "42"}]}],
    }
    with patch(
        "src.servers.bigquery.main.requests.request", side_effect=[dry_run, response]
    ) as request:
        result = _execute(
            "secret",
            "run_query",
            {"project_id": "my-project", "sql": "SELECT * FROM `my-project.ds.t`"},
            {"my-project"},
        )
    assert result["rows"] == [{"total": "42"}]
    dry_args, dry_kwargs = request.call_args_list[0]
    assert dry_args == (
        "POST",
        "https://bigquery.googleapis.com/bigquery/v2/projects/my-project/jobs",
    )
    assert dry_kwargs["json"]["configuration"]["dryRun"] is True
    assert dry_kwargs["json"]["configuration"]["query"]["useLegacySql"] is False
    args, kwargs = request.call_args_list[1]
    assert args == (
        "POST",
        "https://bigquery.googleapis.com/bigquery/v2/projects/my-project/queries",
    )
    assert kwargs["json"]["maximumBytesBilled"] == "1000000000"
    assert kwargs["json"]["useLegacySql"] is False
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_query_result_page_preserves_token_and_location():
    job_response = Mock()
    job_response.json.return_value = {
        "jobReference": {"projectId": "p", "jobId": "job/1"}
    }
    response = Mock()
    response.json.return_value = {"jobComplete": False, "rows": [], "pageToken": "next"}
    with patch(
        "src.servers.bigquery.main.requests.request",
        side_effect=[job_response, response],
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
            {"p"},
        )
    assert result["pageToken"] == "next"
    assert request.call_args_list[0].args[1].endswith("/projects/p/jobs/job%2F1")
    assert request.call_args.args[1].endswith("/projects/p/queries/job%2F1")
    assert request.call_args.kwargs["params"]["location"] == "asia-southeast1"


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("list_datasets", {"project_id": "other-project"}),
        ("list_tables", {"project_id": "other-project", "dataset_id": "ds"}),
        (
            "get_table",
            {"project_id": "other-project", "dataset_id": "ds", "table_id": "t"},
        ),
        ("run_query", {"project_id": "other-project", "sql": "SELECT 1"}),
        ("get_query_results", {"project_id": "other-project", "job_id": "j"}),
    ],
)
def test_every_tool_rejects_disallowed_project_before_http(name, arguments):
    with patch("src.servers.bigquery.main.requests.request") as request:
        with pytest.raises(ValueError, match="project is not allowed"):
            _execute("secret", name, arguments, {"allowed-project"})
    request.assert_not_called()


def _dry_run_response(*, tables=None, routines=None, **query_fields):
    response = Mock()
    query = {"statementType": "SELECT"}
    if tables is not None:
        query["referencedTables"] = tables
    if routines is not None:
        query["referencedRoutines"] = routines
    query.update(query_fields)
    response.json.return_value = {
        "configuration": {"dryRun": True, "query": {}},
        "statistics": {"query": query},
    }
    return response


def test_cross_project_reference_from_allowed_job_project_is_rejected():
    dry_run = _dry_run_response(
        tables=[{"projectId": "other-project", "datasetId": "ds", "tableId": "t"}]
    )
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=dry_run
    ) as request:
        with pytest.raises(ValueError, match="disallowed project"):
            _execute(
                "secret",
                "run_query",
                {
                    "project_id": "allowed-project",
                    "sql": "SELECT * FROM `other-project.ds.t`",
                },
                {"allowed-project"},
            )
    assert request.call_count == 1  # dry run only; execution never reached


def test_dry_run_api_failure_is_rejected():
    response = Mock(status_code=400, reason="Bad Request")
    response.raise_for_status.side_effect = requests.HTTPError("400")
    response.json.return_value = {"error": {"message": "Invalid query"}}
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=response
    ) as request:
        with pytest.raises(ValueError, match="Invalid query"):
            _execute(
                "secret", "run_query", {"project_id": "p", "sql": "SELECT 1"}, {"p"}
            )
    assert request.call_count == 1


def test_dry_run_without_referenced_objects_is_rejected():
    dry_run = _dry_run_response(tables=[])
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=dry_run
    ) as request:
        with pytest.raises(ValueError, match="no referenced objects"):
            _execute(
                "secret", "run_query", {"project_id": "p", "sql": "SELECT 1"}, {"p"}
            )
    assert request.call_count == 1


@pytest.mark.parametrize(
    "sql,tables",
    [
        # INFORMATION_SCHEMA dry runs may not list concrete tables. Even if
        # one is reported, the metadata view itself is not proven scoped.
        ("SELECT * FROM `other-project.ds.INFORMATION_SCHEMA.TABLES`", []),
        # A wildcard dry run can report expanded tables; reject the pattern
        # because a partial expansion would not prove the query's full scope.
        (
            "SELECT * FROM `allowed-project.ds.table_*`",
            [{"projectId": "allowed-project", "datasetId": "ds", "tableId": "table_1"}],
        ),
    ],
)
def test_information_schema_and_wildcard_queries_fail_closed(sql, tables):
    dry_run = _dry_run_response(tables=tables)
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=dry_run
    ) as request:
        with pytest.raises(
            ValueError, match="referenced objects|scope cannot be verified"
        ):
            _execute(
                "secret",
                "run_query",
                {"project_id": "allowed-project", "sql": sql},
                {"allowed-project"},
            )
    assert request.call_count == 1


def test_dry_run_rejects_cross_project_routine_and_destination():
    allowed_table = {"projectId": "p", "datasetId": "ds", "tableId": "t"}
    dry_run = _dry_run_response(
        tables=[allowed_table],
        routines=[{"projectId": "other", "datasetId": "ds", "routineId": "fn"}],
    )
    with patch("src.servers.bigquery.main.requests.request", return_value=dry_run):
        with pytest.raises(ValueError, match="disallowed project"):
            _execute(
                "secret",
                "run_query",
                {"project_id": "p", "sql": "SELECT fn() FROM `p.ds.t`"},
                {"p"},
            )

    dry_run = _dry_run_response(tables=[allowed_table])
    dry_run.json.return_value["configuration"]["query"]["destinationTable"] = {
        "projectId": "other",
        "datasetId": "ds",
        "tableId": "out",
    }
    with patch("src.servers.bigquery.main.requests.request", return_value=dry_run):
        with pytest.raises(ValueError, match="disallowed project"):
            _execute(
                "secret",
                "run_query",
                {"project_id": "p", "sql": "SELECT * FROM `p.ds.t`"},
                {"p"},
            )


def test_get_query_results_verifies_job_project():
    job_response = Mock()
    job_response.json.return_value = {
        "jobReference": {"projectId": "other-project", "jobId": "job-1"}
    }
    with patch(
        "src.servers.bigquery.main.requests.request", return_value=job_response
    ) as request:
        with pytest.raises(ValueError, match="does not belong"):
            _execute(
                "secret",
                "get_query_results",
                {"project_id": "allowed-project", "job_id": "job-1"},
                {"allowed-project"},
            )
    assert request.call_count == 1


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
    auth.get_user_credentials.return_value = {
        "access_token": "oauth-token",
        "metadata": {"allowedProjects": ["project-id"]},
    }
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
@pytest.mark.parametrize(
    "name,arguments",
    [
        ("list_datasets", {"project_id": "p"}),
        ("list_tables", {"project_id": "p", "dataset_id": "ds"}),
        ("get_table", {"project_id": "p", "dataset_id": "ds", "table_id": "t"}),
        ("run_query", {"project_id": "p", "sql": "SELECT 1"}),
        ("get_query_results", {"project_id": "p", "job_id": "j"}),
    ],
)
async def test_missing_allowed_projects_is_mcp_error_for_every_tool(name, arguments):
    auth = Mock()
    auth.get_user_credentials.return_value = {
        "access_token": "oauth-token",
        "metadata": {},
    }
    with patch(
        "src.servers.bigquery.main.create_auth_client", return_value=auth
    ), patch("src.servers.bigquery.main.requests.request") as request:
        result = await create_server("connection-id").dispatch(
            CallToolRequest(
                params=CallToolRequestParams(name=name, arguments=arguments)
            )
        )
    assert result.is_error is True
    assert "allowedProjects" in result.content[0].text
    request.assert_not_called()


@pytest.mark.asyncio
async def test_bigquery_http_failure_is_mcp_error():
    auth = Mock()
    auth.get_user_credentials.return_value = {
        "access_token": "oauth-token",
        "metadata": {"allowedProjects": ["project-id"]},
    }
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
