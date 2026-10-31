"""BigQuery MCP tools backed by a Nango-managed Google OAuth connection."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from src.auth.factory import create_auth_client
from src.utils.mcp_compat import NotificationOptions, Server

SERVICE_NAME = Path(__file__).parent.name
API_URL = "https://bigquery.googleapis.com/bigquery/v2"


def _allowed_projects(credentials: dict) -> set[str]:
    metadata = credentials.get("metadata")
    projects = metadata.get("allowedProjects") if isinstance(metadata, dict) else None
    if (
        not isinstance(projects, list)
        or not projects
        or any(
            not isinstance(project, str) or not project or project != project.strip()
            for project in projects
        )
    ):
        raise ValueError(
            "BigQuery connection has no valid allowedProjects configuration"
        )
    return set(projects)


def _require_project(project_id: str, allowed_projects: set[str]) -> str:
    if not isinstance(project_id, str) or project_id not in allowed_projects:
        raise ValueError(f"BigQuery project is not allowed: {project_id}")
    return _segment(project_id)


def _check_reference(reference: dict, allowed_projects: set[str]) -> None:
    project_id = reference.get("projectId") if isinstance(reference, dict) else None
    if not isinstance(project_id, str) or project_id not in allowed_projects:
        raise ValueError(
            f"BigQuery query references a disallowed project: {project_id}"
        )


def _validate_dry_run(dry_run: dict, sql: str, allowed_projects: set[str]) -> None:
    if dry_run.get("configuration", {}).get("dryRun") is not True:
        raise ValueError("BigQuery did not confirm the dry run")
    if dry_run.get("status", {}).get("errorResult"):
        raise ValueError("BigQuery dry run failed")
    query = dry_run.get("statistics", {}).get("query")
    if not isinstance(query, dict):
        raise ValueError("BigQuery dry run returned no query statistics")
    if query.get("statementType") in {"SCRIPT", "CALL", "EXECUTE_IMMEDIATE"}:
        raise ValueError(
            "BigQuery dry run cannot verify this query's project references"
        )

    references = []
    for field in (
        "referencedTables",
        "referencedRoutines",
        "referencedLogicalViews",
        "referencedPropertyGraphs",
    ):
        value = query.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"BigQuery dry run returned invalid {field}")
        references.extend(value)
    if not references:
        raise ValueError("BigQuery dry run returned no referenced objects")
    for reference in references:
        _check_reference(reference, allowed_projects)

    # BigQuery dry runs are best effort for metadata and wildcard queries. A
    # reference list that omits the expanded objects cannot prove their scope.
    if re.search(r"\bINFORMATION_SCHEMA\b", sql, re.IGNORECASE) or re.search(
        r"`[^`]*\*[^`]*`", sql
    ):
        raise ValueError("BigQuery project scope cannot be verified for this query")

    configuration = dry_run.get("configuration", {}).get("query", {})
    if not isinstance(configuration, dict):
        raise ValueError("BigQuery dry run returned invalid query configuration")
    for reference in (
        configuration.get("destinationTable"),
        query.get("ddlTargetTable"),
        query.get("ddlDestinationTable"),
        query.get("ddlTargetRoutine"),
        query.get("ddlTargetDataset"),
        query.get("dclTargetTable"),
        query.get("dclTargetView"),
        query.get("dclTargetDataset"),
    ):
        if reference is not None:
            _check_reference(reference, allowed_projects)


def _dry_run(token: str, project: str, body: dict, allowed_projects: set[str]) -> None:
    query_config = {
        "query": body["query"],
        "useLegacySql": False,
        "maximumBytesBilled": body["maximumBytesBilled"],
    }
    job = {
        "configuration": {"dryRun": True, "query": query_config},
        "jobReference": {"projectId": project},
    }
    if body.get("location"):
        job["jobReference"]["location"] = body["location"]
    result = _request(token, "POST", f"/projects/{_segment(project)}/jobs", body=job)
    _validate_dry_run(result, body["query"], allowed_projects)


def _segment(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "Project, dataset, table, and job IDs must be non-empty strings"
        )
    return quote(value, safe="")


def _request(token: str, method: str, path: str, *, params=None, body=None) -> dict:
    response = requests.request(
        method,
        f"{API_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        json=body,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Google error messages help diagnose IAM and billing configuration.
        try:
            message = response.json().get("error", {}).get("message", response.reason)
        except ValueError:
            message = response.reason
        raise ValueError(
            f"BigQuery API error ({response.status_code}): {message}"
        ) from exc
    return response.json()


def _page_size(arguments: dict) -> int:
    size = arguments.get("max_results", 100)
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 1000:
        raise ValueError("max_results must be an integer between 1 and 1000")
    return size


def _query_rows(data: dict) -> dict:
    fields = data.get("schema", {}).get("fields", [])
    if fields:
        data["rows"] = [
            {
                field["name"]: cell.get("v")
                for field, cell in zip(fields, row.get("f", []))
            }
            for row in data.get("rows", [])
        ]
    return data


def _execute(
    token: str, name: str, arguments: dict, allowed_projects: set[str]
) -> dict:
    project_id = arguments["project_id"]
    project = _require_project(project_id, allowed_projects)
    if name == "list_datasets":
        return _request(
            token,
            "GET",
            f"/projects/{project}/datasets",
            params={
                "maxResults": _page_size(arguments),
                "pageToken": arguments.get("page_token"),
            },
        )
    if name == "list_tables":
        dataset = _segment(arguments["dataset_id"])
        return _request(
            token,
            "GET",
            f"/projects/{project}/datasets/{dataset}/tables",
            params={
                "maxResults": _page_size(arguments),
                "pageToken": arguments.get("page_token"),
            },
        )
    if name == "get_table":
        dataset = _segment(arguments["dataset_id"])
        table = _segment(arguments["table_id"])
        return _request(
            token,
            "GET",
            f"/projects/{project}/datasets/{dataset}/tables/{table}",
            params={"view": "BASIC"},
        )
    if name == "run_query":
        sql = arguments["sql"]
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("sql must be a non-empty string")
        billing_limit = arguments.get("maximum_bytes_billed", "1000000000")
        if not str(billing_limit).isdigit() or int(billing_limit) < 1:
            raise ValueError("maximum_bytes_billed must be a positive integer")
        body = {
            "query": sql,
            "useLegacySql": False,
            "maxResults": _page_size(arguments),
            "maximumBytesBilled": str(billing_limit),
            "timeoutMs": 10000,
        }
        if arguments.get("location"):
            body["location"] = arguments["location"]
        _dry_run(token, project_id, body, allowed_projects)
        return _query_rows(
            _request(token, "POST", f"/projects/{project}/queries", body=body)
        )
    if name == "get_query_results":
        job = _segment(arguments["job_id"])
        params = {
            "maxResults": _page_size(arguments),
            "pageToken": arguments.get("page_token"),
        }
        if arguments.get("location"):
            params["location"] = arguments["location"]
        job_details = _request(
            token,
            "GET",
            f"/projects/{project}/jobs/{job}",
            params={"location": arguments.get("location")},
        )
        job_reference = job_details.get("jobReference", {})
        if (
            job_reference.get("projectId") != project_id
            or job_reference.get("jobId") != arguments["job_id"]
        ):
            raise ValueError(
                "BigQuery query job does not belong to the allowed project"
            )
        return _query_rows(
            _request(token, "GET", f"/projects/{project}/queries/{job}", params=params)
        )
    raise ValueError(f"Unknown BigQuery tool: {name}")


def create_server(user_id: str, api_key: str = None) -> Server:
    server = Server("bigquery-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        project = {"type": "string", "description": "Google Cloud project ID"}
        page = {
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 100,
            },
            "page_token": {
                "type": "string",
                "description": "Next page token from a previous response",
            },
        }
        return [
            Tool(
                name="list_datasets",
                description="List accessible BigQuery datasets in a project",
                inputSchema={
                    "type": "object",
                    "properties": {"project_id": project, **page},
                    "required": ["project_id"],
                },
            ),
            Tool(
                name="list_tables",
                description="List tables in a BigQuery dataset",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": project,
                        "dataset_id": {"type": "string"},
                        **page,
                    },
                    "required": ["project_id", "dataset_id"],
                },
            ),
            Tool(
                name="get_table",
                description="Get BigQuery table metadata and schema",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": project,
                        "dataset_id": {"type": "string"},
                        "table_id": {"type": "string"},
                    },
                    "required": ["project_id", "dataset_id", "table_id"],
                },
            ),
            Tool(
                name="run_query",
                description="Run GoogleSQL in BigQuery; statements may modify data. Defaults to a 1 GB billing limit. If jobComplete is false, call get_query_results with the returned jobReference.jobId and location.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": project,
                        "sql": {"type": "string"},
                        "location": {"type": "string"},
                        "max_results": page["max_results"],
                        "maximum_bytes_billed": {
                            "type": "string",
                            "default": "1000000000",
                        },
                    },
                    "required": ["project_id", "sql"],
                },
            ),
            Tool(
                name="get_query_results",
                description="Get or page results for a BigQuery query job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": project,
                        "job_id": {"type": "string"},
                        "location": {"type": "string"},
                        **page,
                    },
                    "required": ["project_id", "job_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        credentials = create_auth_client(api_key=api_key).get_user_credentials(
            SERVICE_NAME, user_id
        )
        token = (credentials or {}).get("access_token") or (credentials or {}).get(
            "token"
        )
        if not token:
            raise ValueError("BigQuery OAuth connection has no access token")
        allowed_projects = _allowed_projects(credentials)
        result = await asyncio.to_thread(
            _execute, token, name, arguments or {}, allowed_projects
        )
        return [TextContent(type="text", text=json.dumps(result))]

    return server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="bigquery-server",
        server_version="0.1.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(), experimental_capabilities={}
        ),
    )


server = create_server
