"""
Google Analytics 4 (GA4) MCP Server

Exposes tools for:
- Listing GA4 properties
- Running custom reports (sessions, users, engagement, traffic sources)
- Getting real-time analytics
- Retrieving available dimensions and metrics metadata
"""

import os
import sys
import logging
import json
from pathlib import Path
from datetime import datetime

# Add project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    RunRealtimeReportRequest,
    GetMetadataRequest,
    DateRange,
    Dimension,
    Metric,
    FilterExpression,
    Filter,
)
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient

from src.auth.factory import create_auth_client

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ga4-server")

SERVICE_NAME = Path(__file__).parent.name  # "ga4"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


async def get_credentials(user_id, api_key=None):
    """Get Google OAuth2 credentials for the specified user.

    Args:
        user_id (str): The identifier of the user whose credentials are needed.
        api_key (Optional[str]): Optional API key for different environments.

    Returns:
        Credentials: The Google OAuth2 credentials for the specified user.

    Raises:
        ValueError: If no valid credentials can be found.
    """
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    if not credentials_data:
        error_str = f"Credentials not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += " Please run with 'auth' argument first."
        logger.error(error_str)
        raise ValueError(error_str)

    # Handle both token formats (local vs Nango)
    token = credentials_data.get("token")
    if token:
        return Credentials.from_authorized_user_info(credentials_data)

    token = credentials_data.get("access_token")
    if token:
        return Credentials(token=token)

    raise ValueError(f"No valid token in credentials for user {user_id}")


def _create_data_client(credentials):
    """Create a GA4 Data API client with the given credentials."""
    return BetaAnalyticsDataClient(credentials=credentials)


def _create_admin_client(credentials):
    """Create a GA4 Admin API client with the given credentials."""
    return AnalyticsAdminServiceClient(credentials=credentials)


def create_server(user_id, api_key=None):
    """Create a new MCP server instance for Google Analytics 4.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key.

    Returns:
        Server: Configured MCP server with GA4 tools.
    """
    server = Server("ga4-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available GA4 tools."""
        return [
            types.Tool(
                name="list_properties",
                description="List all GA4 properties accessible to the user",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            types.Tool(
                name="run_report",
                description="Run a custom GA4 report with configurable dimensions and metrics, with optional page path filter. Use this for sessions, users, engagement rate, traffic sources, etc.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "GA4 property ID (numeric, e.g., 123456789). Do NOT include 'properties/' prefix.",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date (YYYY-MM-DD or relative like '30daysAgo', '7daysAgo')",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date (YYYY-MM-DD or 'today', 'yesterday')",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Metrics to include: sessions, totalUsers, newUsers, engagementRate, screenPageViews, averageSessionDuration, bounceRate, conversions, etc.",
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to group by: pagePath, sessionSource, sessionMedium, sessionSourceMedium, date, country, city, deviceCategory, etc.",
                        },
                        "page_path_filter": {
                            "type": "string",
                            "description": "Optional exact pagePath to filter (e.g., /blog/finance-automation-roi-guide-cfo)",
                        },
                        "row_limit": {
                            "type": "integer",
                            "description": "Max rows to return (default: 25, max: 100000)",
                        },
                    },
                    "required": ["property_id", "start_date", "end_date", "metrics"],
                },
            ),
            types.Tool(
                name="get_realtime_report",
                description="Get real-time analytics data for a GA4 property (active users, page views, etc.)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "GA4 property ID (numeric, e.g., 123456789)",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Real-time metrics: activeUsers, screenPageViews, conversions, eventCount, etc.",
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Real-time dimensions: unifiedScreenName, country, city, deviceCategory, etc.",
                        },
                    },
                    "required": ["property_id", "metrics"],
                },
            ),
            types.Tool(
                name="get_metadata",
                description="Get available dimensions and metrics metadata for a GA4 property. Useful for discovering what metrics and dimensions can be used in reports.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "GA4 property ID (numeric, e.g., 123456789)",
                        },
                    },
                    "required": ["property_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch and handle tool execution."""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        try:
            credentials = await get_credentials(server.user_id, server.api_key)

            if name == "list_properties":
                return await _list_properties(credentials)
            elif name == "run_report":
                return await _run_report(credentials, arguments)
            elif name == "get_realtime_report":
                return await _get_realtime_report(credentials, arguments)
            elif name == "get_metadata":
                return await _get_metadata(credentials, arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)}),
                )
            ]

    return server


def _normalize_property_id(property_id: str) -> str:
    """Ensure property_id has the 'properties/' prefix."""
    if property_id.startswith("properties/"):
        return property_id
    return f"properties/{property_id}"


async def _list_properties(credentials) -> list[types.TextContent]:
    """List all GA4 properties accessible to the user."""
    admin_client = _create_admin_client(credentials)

    # List account summaries which include properties
    account_summaries = admin_client.list_account_summaries()

    properties = []
    for summary in account_summaries:
        account_name = summary.display_name
        account_id = summary.account
        for prop_summary in summary.property_summaries:
            properties.append(
                {
                    "propertyId": prop_summary.property.replace("properties/", ""),
                    "propertyName": prop_summary.display_name,
                    "propertyResource": prop_summary.property,
                    "accountName": account_name,
                    "accountId": account_id,
                }
            )

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {"properties": properties, "totalProperties": len(properties)},
                indent=2,
            ),
        )
    ]


async def _run_report(credentials, arguments: dict) -> list[types.TextContent]:
    """Run a custom GA4 report with dimensions, metrics, and optional page path filter."""
    property_id = _normalize_property_id(arguments["property_id"])
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    metrics = arguments["metrics"]
    dimensions = arguments.get("dimensions", [])
    page_path_filter = arguments.get("page_path_filter")
    row_limit = arguments.get("row_limit", 25)

    # Clamp row_limit
    row_limit = max(1, min(row_limit, 100000))

    client = _create_data_client(credentials)

    # Build request
    request = RunReportRequest(
        property=property_id,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        metrics=[Metric(name=m) for m in metrics],
        dimensions=[Dimension(name=d) for d in dimensions] if dimensions else [],
        limit=row_limit,
    )

    # Add page path filter if specified
    if page_path_filter:
        request.dimension_filter = FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.EXACT,
                    value=page_path_filter,
                ),
            )
        )

    response = client.run_report(request)

    # Format the response
    dimension_headers = [h.name for h in response.dimension_headers]
    metric_headers = [h.name for h in response.metric_headers]

    rows = []
    for row in response.rows:
        formatted_row = {}
        for i, dim_value in enumerate(row.dimension_values):
            formatted_row[dimension_headers[i]] = dim_value.value
        for i, met_value in enumerate(row.metric_values):
            formatted_row[metric_headers[i]] = met_value.value
        rows.append(formatted_row)

    # Include totals if available
    totals = {}
    if response.totals:
        for total_row in response.totals:
            for i, met_value in enumerate(total_row.metric_values):
                totals[metric_headers[i]] = met_value.value

    result = {
        "propertyId": property_id,
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimension_headers,
        "metrics": metric_headers,
        "rows": rows,
        "totalRows": len(rows),
        "rowCount": response.row_count,
    }

    if totals:
        result["totals"] = totals
    if page_path_filter:
        result["pagePathFilter"] = page_path_filter

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2),
        )
    ]


async def _get_realtime_report(credentials, arguments: dict) -> list[types.TextContent]:
    """Get real-time analytics data for a GA4 property."""
    property_id = _normalize_property_id(arguments["property_id"])
    metrics = arguments["metrics"]
    dimensions = arguments.get("dimensions", [])

    client = _create_data_client(credentials)

    request = RunRealtimeReportRequest(
        property=property_id,
        metrics=[Metric(name=m) for m in metrics],
        dimensions=[Dimension(name=d) for d in dimensions] if dimensions else [],
    )

    response = client.run_realtime_report(request)

    # Format the response
    dimension_headers = [h.name for h in response.dimension_headers]
    metric_headers = [h.name for h in response.metric_headers]

    rows = []
    for row in response.rows:
        formatted_row = {}
        for i, dim_value in enumerate(row.dimension_values):
            formatted_row[dimension_headers[i]] = dim_value.value
        for i, met_value in enumerate(row.metric_values):
            formatted_row[metric_headers[i]] = met_value.value
        rows.append(formatted_row)

    # Include totals if available
    totals = {}
    if response.totals:
        for total_row in response.totals:
            for i, met_value in enumerate(total_row.metric_values):
                totals[metric_headers[i]] = met_value.value

    result = {
        "propertyId": property_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "dimensions": dimension_headers,
        "metrics": metric_headers,
        "rows": rows,
        "totalRows": len(rows),
        "rowCount": response.row_count,
    }

    if totals:
        result["totals"] = totals

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2),
        )
    ]


async def _get_metadata(credentials, arguments: dict) -> list[types.TextContent]:
    """Get available dimensions and metrics for a GA4 property."""
    property_id = _normalize_property_id(arguments["property_id"])

    client = _create_data_client(credentials)

    request = GetMetadataRequest(name=f"{property_id}/metadata")
    response = client.get_metadata(request)

    # Format dimensions
    dimensions_list = []
    for dim in response.dimensions:
        dimensions_list.append(
            {
                "apiName": dim.api_name,
                "uiName": dim.ui_name,
                "description": dim.description,
                "category": dim.category,
            }
        )

    # Format metrics
    metrics_list = []
    for met in response.metrics:
        metrics_list.append(
            {
                "apiName": met.api_name,
                "uiName": met.ui_name,
                "description": met.description,
                "category": met.category,
                "type": met.type_.name if met.type_ else None,
            }
        )

    result = {
        "propertyId": property_id,
        "totalDimensions": len(dimensions_list),
        "totalMetrics": len(metrics_list),
        "dimensions": dimensions_list,
        "metrics": metrics_list,
    }

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2),
        )
    ]


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get MCP initialization options for this server."""
    return InitializationOptions(
        server_name="ga4",
        server_version="0.1.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Export for auto-discovery by remote.py
server = create_server

if __name__ == "__main__":
    import asyncio
    from src.servers.local import run_local_server

    asyncio.run(run_local_server(create_server, get_initialization_options))
